"""Generic schema.org JobPosting fallback with robots.txt compliance."""
from __future__ import annotations

import html as html_mod
import json
import re
from urllib.parse import urlparse

from ..config import settings
from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting, RobotsPolicy
from .greenhouse import html_to_text

_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_ROBOTS = RobotsPolicy(settings().robots_cache_ttl_hours)


def _iter_jobpostings(node) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(str(x).lower() == "jobposting" for x in types if x):
            found.append(node)
        for value in node.values():
            found.extend(_iter_jobpostings(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_iter_jobpostings(value))
    return found


class JsonLdSource(JobSource):
    provider = "jsonld"

    async def fetch(self, token: str) -> list[RawPosting]:
        url = token
        if not await _ROBOTS.allowed(self.client, url):
            return []

        html = await self.client.get_text(url)
        if not html:
            return []

        out: list[RawPosting] = []
        for block in _LD.findall(html):
            raw_block = html_mod.unescape(block).strip()
            try:
                parsed = json.loads(raw_block)
            except json.JSONDecodeError:
                continue

            for jp in _iter_jobpostings(parsed):
                org = jp.get("hiringOrganization") or {}
                if isinstance(org, list):
                    org = org[0] if org else {}
                loc = jp.get("jobLocation") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = loc.get("address") if isinstance(loc, dict) else {}
                addr = addr if isinstance(addr, dict) else {}

                job_location_type = str(jp.get("jobLocationType") or "").upper()
                if job_location_type == "TELECOMMUTE":
                    loc_str = "Remote"
                else:
                    loc_str = ", ".join(
                        filter(
                            None,
                            [
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("addressCountry"),
                            ],
                        )
                    )

                sal = jp.get("baseSalary") or {}
                val = sal.get("value") if isinstance(sal, dict) else {}
                val = val if isinstance(val, dict) else {}
                identifier = jp.get("identifier")
                if isinstance(identifier, dict):
                    identifier = identifier.get("value")

                external = identifier or jp.get("url") or jp.get("title")
                title = clean_text(jp.get("title"))
                if not external or not title:
                    continue

                out.append(
                    RawPosting(
                        external_id=str(external),
                        title=title,
                        url=str(jp.get("url") or url),
                        description=html_to_text(jp.get("description")) or None,
                        location_raw=clean_text(loc_str) or None,
                        employment_type=clean_text(jp.get("employmentType")) or None,
                        remote_hint="remote" if job_location_type == "TELECOMMUTE" else None,
                        posted_at=parse_datetime(jp.get("datePosted")),
                        updated_at=parse_datetime(jp.get("dateModified")),
                        salary_min=val.get("minValue"),
                        salary_max=val.get("maxValue"),
                        salary_currency=val.get("currency") or (
                            sal.get("currency") if isinstance(sal, dict) else None
                        ),
                        company_name=clean_text(org.get("name")) if isinstance(org, dict) else None,
                        company_website=org.get("sameAs") if isinstance(org, dict) else None,
                        raw={"source_url": url, "schema_type": "JobPosting"},
                    )
                )
        return out
