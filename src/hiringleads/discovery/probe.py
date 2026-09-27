"""Board discovery: cheap domain probes first, Common Crawl second."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import structlog

from ..normalize import clean_text, slugify
from ..sources.base import HttpClient

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class DiscoveredBoard:
    provider: str
    token: str
    url: str
    company_name: str | None = None
    company_domain: str | None = None
    discovered_via: str = "probe"


PROBE_PATTERNS: list[tuple[str, str]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{token}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{token}"),
    ("workable", "https://www.workable.com/api/accounts/{token}?details=true"),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=1"),
    ("recruitee", "https://{token}.recruitee.com/api/offers/"),
]

# Primary providers cover the common ATS path; the rest are fallbacks so a
# failed probe doesn't create a 36-request burst for every domain.
PRIMARY_PROVIDERS = {"greenhouse", "lever"}
_TOKEN_VARIANTS = (
    "{slug}",
    "{slug}inc",
    "{slug}-inc",
    "{slug}careers",
    "{slug}-careers",
    "{slug}jobs",
)
PROVIDER_TO_PATTERNS = {provider: pattern for provider, pattern in PROBE_PATTERNS}


def _candidate_tokens(domain: str) -> list[str]:
    root = domain.lower().removeprefix("www.").split(".")[0]
    slug = slugify(root)
    return [variant.format(slug=slug) for variant in _TOKEN_VARIANTS]


async def _probe_provider(
    client: HttpClient,
    provider: str,
    tokens: list[str],
    *,
    timeout: float,
) -> list[DiscoveredBoard]:
    pattern = PROVIDER_TO_PATTERNS[provider]

    async def try_one(token: str) -> DiscoveredBoard | None:
        url = pattern.format(token=token)
        try:
            data = await asyncio.wait_for(client.get_json(url), timeout=timeout)
        except Exception:
            return None

        has_jobs = (
            isinstance(data, list) and bool(data)
        ) or (
            isinstance(data, dict)
            and any(data.get(key) for key in ("jobs", "offers", "content"))
        )
        if not has_jobs:
            return None

        return DiscoveredBoard(
            provider=provider,
            token=token,
            url=url,
            discovered_via="probe",
        )

    results = await asyncio.gather(*(try_one(token) for token in tokens))
    # One provider/token is enough. De-duplicate aliases that happen to hit the same board.
    seen: set[tuple[str, str]] = set()
    out = []
    for result in results:
        if result and (result.provider, result.token) not in seen:
            seen.add((result.provider, result.token))
            out.append(result)
    return out


async def probe_domain(
    client: HttpClient,
    domain: str,
    *,
    total_timeout: float = 20.0,
    per_probe_timeout: float = 6.0,
) -> list[DiscoveredBoard]:
    """Probe primary ATSs first, then fall back only if no primary match exists."""
    clean_domain = domain.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0]
    tokens = _candidate_tokens(clean_domain)

    async def run() -> list[DiscoveredBoard]:
        primary: list[DiscoveredBoard] = []
        for provider in sorted(PRIMARY_PROVIDERS):
            found = await _probe_provider(
                client,
                provider,
                tokens,
                timeout=per_probe_timeout,
            )
            primary.extend(found)

        if primary:
            return primary

        fallback = []
        for provider, _ in PROBE_PATTERNS:
            if provider in PRIMARY_PROVIDERS:
                continue
            fallback.extend(
                await _probe_provider(
                    client,
                    provider,
                    tokens,
                    timeout=per_probe_timeout,
                )
            )
        return fallback

    try:
        return await asyncio.wait_for(run(), timeout=total_timeout)
    except asyncio.TimeoutError:
        log.warning("probe.timeout", domain=clean_domain, timeout=total_timeout)
        return []


CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_TARGETS: list[tuple[str, str, re.Pattern[str]]] = [
    ("greenhouse", "boards.greenhouse.io/*", re.compile(r"boards\.greenhouse\.io/([^/?#]+)", re.I)),
    ("greenhouse", "job-boards.greenhouse.io/*", re.compile(r"job-boards\.greenhouse\.io/([^/?#]+)", re.I)),
    ("lever", "jobs.lever.co/*", re.compile(r"jobs\.lever\.co/([^/?#]+)", re.I)),
    ("ashby", "jobs.ashbyhq.com/*", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)", re.I)),
    ("workable", "apply.workable.com/*", re.compile(r"apply\.workable\.com/([^/?#]+)", re.I)),
    ("smartrecruiters", "jobs.smartrecruiters.com/*", re.compile(r"jobs\.smartrecruiters\.com/([^/?#]+)", re.I)),
    ("recruitee", "*.recruitee.com/*", re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
]

_TOKEN_DENYLIST = {
    "api", "www", "jobs", "job", "careers", "boards", "board", "apply",
    "static", "assets", "cdn", "images", "embed", "widget", "js", "css",
    "index", "search",
}


async def latest_cc_index(client: HttpClient) -> str | None:
    try:
        data = await client.get_json(CC_COLLINFO)
    except Exception as exc:
        log.warning("commoncrawl.collinfo_failed", error=str(exc))
        return None
    if isinstance(data, list) and data:
        return clean_text(data[0].get("id")) or None
    return None


async def discover_via_commoncrawl(
    client: HttpClient,
    *,
    index_id: str | None = None,
    pages_per_target: int = 2,
    limit_per_target: int = 5000,
) -> list[DiscoveredBoard]:
    index_id = index_id or await latest_cc_index(client)
    if not index_id:
        return []

    all_out: list[DiscoveredBoard] = []

    for provider, url_pattern, token_re in CC_TARGETS:
        target_out: list[DiscoveredBoard] = []
        seen: set[str] = set()

        for page in range(max(1, pages_per_target)):
            try:
                data = await client.get_json(
                    f"https://index.commoncrawl.org/{index_id}-index",
                    url=url_pattern,
                    output="json",
                    page=page,
                    pageSize=1000,
                )
            except Exception as exc:
                log.warning(
                    "commoncrawl.query_failed",
                    target=url_pattern,
                    page=page,
                    error=str(exc),
                )
                break

            text = data.get("_text", "") if isinstance(data, dict) else ""
            lines = [line for line in text.splitlines() if line.strip()]
            if not lines:
                break

            import orjson

            for line in lines:
                try:
                    record = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue

                url = str(record.get("url") or "")
                match = token_re.search(url)
                if not match:
                    continue
                token = match.group(1).lower().rstrip("/")
                if token in _TOKEN_DENYLIST or len(token) < 2 or len(token) > 200:
                    continue
                if token in seen:
                    continue
                seen.add(token)
                target_out.append(
                    DiscoveredBoard(
                        provider=provider,
                        token=token,
                        url=url,
                        discovered_via="commoncrawl",
                    )
                )
                if len(target_out) >= limit_per_target:
                    break

            if len(target_out) >= limit_per_target:
                break

        all_out.extend(target_out)
        log.info(
            "commoncrawl.target_complete",
            provider=provider,
            found=len(target_out),
        )

    log.info("commoncrawl.discovered", count=len(all_out), index=index_id)
    return all_out


async def hydrate_company(client: HttpClient, board: DiscoveredBoard) -> DiscoveredBoard:
    """Best-effort enrichment; a discovery result stays usable if this fails."""
    try:
        if board.provider == "greenhouse":
            data = await client.get_json(
                f"https://boards-api.greenhouse.io/v1/boards/{board.token}"
            )
            if isinstance(data, dict):
                board.company_name = clean_text(data.get("name")) or board.company_name
        elif board.provider == "workable":
            data = await client.get_json(
                f"https://www.workable.com/api/accounts/{board.token}?details=true"
            )
            if isinstance(data, dict):
                board.company_name = clean_text(data.get("name")) or board.company_name
        elif board.provider in {"lever", "ashby", "smartrecruiters", "recruitee"}:
            board.company_name = board.company_name or clean_text(
                board.token.replace("-", " ").replace("_", " ")
            ).title()
    except Exception as exc:
        log.debug("board.hydrate_failed", provider=board.provider, token=board.token, error=str(exc))
    return board
