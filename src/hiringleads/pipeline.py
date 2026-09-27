"""Durable ingestion pipeline.

Key invariants:
1. ``first_seen_at`` is always the time our system first observed the row.
   Source ``posted_at`` is advisory and never overwrites that truth.
2. Board-level advisory locking prevents duplicate concurrent scans.
3. Near-duplicate matching is in-memory and bucketed; there is no N+1 SQL loop.
4. Empty provider responses never deactivate a whole board.
5. Provider payloads are sanitized before being persisted.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .classify import Classification, classify
from .config import settings
from .dedupe import best_fuzzy_match
from .enrich.company import infer_open_roles_band, registrable_domain
from .models import ClassificationReview, Company, IngestionRun, JobBoard, JobPosting, utcnow
from .normalize import (
    canonical_url,
    clean_text,
    content_hash,
    dedupe_bucket,
    dedupe_key,
    normalize_title,
    parse_location,
    parse_seniority,
    slugify,
    truncate,
)
from .observability import (
    ACTIVE_BOARDS,
    BOARDS_SCANNED,
    BULK_SYNCS,
    INGEST_DURATION,
    POSTINGS_CREATED,
    POSTINGS_DEACTIVATED,
    POSTINGS_DEDUPED,
    POSTINGS_UPDATED,
)
from .sanitize import sanitize_description, sanitize_raw
from .sources.base import HttpClient
from .sources.registry import get_source_class

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class BoardResult:
    board_id: int
    provider: str
    token: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    deduped: int = 0
    reposts: int = 0
    error: str | None = None
    bulk_sync: bool = False
    empty_response: bool = False
    new_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


async def _get_or_create_company(
    session: AsyncSession,
    *,
    name: str,
    slug: str,
    domain: str | None,
    website: str | None = None,
) -> Company:
    stmt = (
        pg_insert(Company)
        .values(
            name=name[:300],
            slug=slug,
            domain=domain,
            website=website,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    await session.execute(stmt)
    company = (
        await session.execute(select(Company).where(Company.slug == slug))
    ).scalar_one()

    changed = False
    if domain and not company.domain:
        company.domain = domain
        changed = True
    if website and not company.website:
        company.website = website
        changed = True
    if name and company.name != name[:300] and company.name.startswith("Unknown"):
        company.name = name[:300]
        changed = True
    if changed:
        company.updated_at = utcnow()
    return company


async def upsert_board(
    session: AsyncSession,
    *,
    provider: str,
    token: str,
    url: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
    discovered_via: str = "manual",
) -> JobBoard:
    token = clean_text(token)
    provider = clean_text(provider).lower()
    name = clean_text(company_name) or token.replace("-", " ").replace("_", " ").title()
    slug = slugify(name)
    domain = registrable_domain(company_domain or url)

    company = await _get_or_create_company(
        session,
        name=name or "Unknown company",
        slug=slug,
        domain=domain,
        website=canonical_url(company_domain),
    )

    stmt = (
        pg_insert(JobBoard)
        .values(
            company_id=company.id,
            provider=provider,
            token=token[:500],
            url=canonical_url(url),
            discovered_via=discovered_via,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["provider", "token"])
    )
    await session.execute(stmt)
    board = (
        await session.execute(
            select(JobBoard).where(
                JobBoard.provider == provider,
                JobBoard.token == token,
            )
        )
    ).scalar_one()

    if url and not board.url:
        board.url = canonical_url(url)
    if discovered_via and not board.discovered_via:
        board.discovered_via = discovered_via
    if board.company_id != company.id:
        # Preserve the first verified company mapping rather than silently moving
        # a live board when discovery generates a weaker name.
        log.warning(
            "board.company_mapping_conflict",
            board_id=board.id,
            existing_company_id=board.company_id,
            candidate_company_id=company.id,
        )
    return board


async def _insert_review(
    session: AsyncSession,
    row: JobPosting,
    cls: Classification,
) -> None:
    s = settings()
    if cls.confidence >= s.low_confidence_threshold:
        return

    existing = await session.get(ClassificationReview, row.id)
    if existing is not None:
        if existing.reviewed_at is None:
            existing.predicted_family = cls.role_family
            existing.confidence = cls.confidence
            existing.evidence = cls.evidence
        return

    session.add(
        ClassificationReview(
            job_id=row.id,
            predicted_family=cls.role_family,
            confidence=cls.confidence,
            evidence=cls.evidence,
        )
    )


def _apply_row_update(
    row: JobPosting,
    *,
    raw,
    norm_title: str,
    loc: dict[str, str | None],
    remote_type: str,
    seniority: str | None,
    cls: Classification,
    chash: str,
) -> None:
    row.title = truncate(clean_text(raw.title), 400) or row.title
    row.normalized_title = norm_title[:400]
    row.description = sanitize_description(raw.description)
    row.location_raw = truncate(clean_text(raw.location_raw), 300)
    row.city = truncate(loc["city"], 120)
    row.region = truncate(loc["region"], 120)
    row.country = loc["country"]
    row.remote_type = remote_type
    row.department = truncate(clean_text(raw.department), 200)
    row.employment_type = truncate(clean_text(raw.employment_type), 60)
    row.seniority = seniority
    row.role_family = cls.role_family
    row.role_family_confidence = cls.confidence
    row.classification_evidence = cls.evidence
    row.skills = cls.skills
    row.salary_min = raw.salary_min
    row.salary_max = raw.salary_max
    row.salary_currency = clean_text(raw.salary_currency).upper()[:3] or None
    row.url = truncate(canonical_url(raw.url), 1000) or row.url
    row.apply_url = truncate(canonical_url(raw.apply_url), 1000)
    row.posted_at = raw.posted_at
    row.updated_at_source = raw.updated_at
    row.content_hash = chash
    row.raw = sanitize_raw(raw.raw if isinstance(raw.raw, dict) else {})


async def ingest_board(
    session: AsyncSession,
    board: JobBoard,
    client: HttpClient,
) -> BoardResult:
    s = settings()
    source = get_source_class(board.provider)(client)
    result = BoardResult(board_id=board.id, provider=board.provider, token=board.token)
    started = time.perf_counter()
    now = utcnow()

    await session.execute(select(func.pg_advisory_xact_lock(1, board.id)))
    board.last_started_at = now

    run = IngestionRun(board_id=board.id, status="running", started_at=now)
    session.add(run)
    await session.flush()

    try:
        raw = await source.fetch(board.token)
    except Exception as exc:
        board.consecutive_failures += 1
        board.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        result.error = board.last_error
        run.status = "failed"
        run.error = result.error

        if board.consecutive_failures >= 5:
            board.is_active = False
            log.warning(
                "board.disabled",
                board_id=board.id,
                provider=board.provider,
                token=board.token,
            )

        BOARDS_SCANNED.labels(board.provider, "error").inc()
        INGEST_DURATION.labels(board.provider).observe(time.perf_counter() - started)
        _finish_run(run, started, result)
        log.warning(
            "ingest.board_failed",
            board_id=board.id,
            provider=board.provider,
            token=board.token,
            error=result.error,
        )
        return result

    result.fetched = len(raw)
    prev_count = board.last_job_count or 0
    result.bulk_sync = (
        len(raw) >= s.bulk_post_threshold
        and (prev_count == 0 or len(raw) > prev_count * s.bulk_growth_factor)
    )
    result.empty_response = len(raw) == 0

    board.consecutive_failures = 0
    board.last_error = None
    board.last_ok_at = now
    board.last_job_count = len(raw)
    board.empty_streak = board.empty_streak + 1 if result.empty_response else 0

    if result.bulk_sync:
        BULK_SYNCS.inc()

    if not raw:
        # An empty JSON response is ambiguous: an empty board and a provider
        # anomaly look identical. Never mass-deactivate on it.
        BOARDS_SCANNED.labels(board.provider, "empty").inc()
        INGEST_DURATION.labels(board.provider).observe(time.perf_counter() - started)
        run.status = "empty"
        _finish_run(run, started, result)
        return result

    existing_by_external = {
        posting.external_id: posting
        for posting in (
            await session.execute(
                select(JobPosting).where(JobPosting.board_id == board.id)
            )
        ).scalars()
    }

    cutoff = now - dt.timedelta(days=s.dedupe_window_days)
    recent_company_postings = list(
        (
            await session.execute(
                select(JobPosting).where(
                    JobPosting.company_id == board.company_id,
                    JobPosting.last_seen_at >= cutoff,
                    JobPosting.is_active.is_(True),
                )
            )
        ).scalars()
    )
    by_bucket: dict[str, list[JobPosting]] = defaultdict(list)
    for posting in recent_company_postings:
        by_bucket[posting.dedupe_bucket].append(posting)

    repost_cutoff = now - dt.timedelta(days=s.repost_window_days)
    inactive_company_postings = list(
        (
            await session.execute(
                select(JobPosting)
                .where(
                    JobPosting.company_id == board.company_id,
                    JobPosting.last_seen_at >= repost_cutoff,
                    JobPosting.is_active.is_(False),
                )
                .order_by(JobPosting.last_seen_at.desc())
                .limit(1000)
            )
        ).scalars()
    )
    inactive_by_bucket: dict[str, list[JobPosting]] = defaultdict(list)
    for posting in inactive_company_postings:
        inactive_by_bucket[posting.dedupe_bucket].append(posting)

    seen_ids: set[str] = set()
    new_reviews: list[tuple[JobPosting, Classification]] = []

    company = board.company

    for item in raw:
        external_id = clean_text(item.external_id)[:200]
        title = clean_text(item.title)
        if not external_id:
            continue
        seen_ids.add(external_id)
        if not title:
            continue

        provider_domain = registrable_domain(item.company_website)
        if provider_domain and not company.domain:
            company.domain = provider_domain
            company.website = canonical_url(item.company_website)

        # Provider anomalies sometimes repeat the same ID in one response.
        if external_id in existing_by_external:
            row = existing_by_external[external_id]
            norm_title = normalize_title(title)
            loc = parse_location(item.location_raw)
            remote_type = loc["remote_type"] if not item.remote_hint else (
                item.remote_hint if item.remote_hint in {"remote", "hybrid", "onsite", "unknown"} else loc["remote_type"]
            )
            seniority = parse_seniority(title, item.description)
            cls = classify(title, item.description, item.department, seniority)
            chash = content_hash(
                title,
                item.description,
                item.location_raw,
                item.department,
                item.employment_type,
                item.remote_hint,
                str(item.salary_min),
                str(item.salary_max),
                item.salary_currency,
                item.apply_url,
            )

            row.last_seen_at = now
            row.missed_scans = 0
            row.is_active = True

            if row.content_hash != chash:
                _apply_row_update(
                    row,
                    raw=item,
                    norm_title=norm_title,
                    loc=loc,
                    remote_type=remote_type,
                    seniority=seniority,
                    cls=cls,
                    chash=chash,
                )
                result.updated += 1
                POSTINGS_UPDATED.inc()

                await session.flush()
                if row.id:
                    new_reviews.append((row, cls))
            else:
                result.unchanged += 1
            continue

        norm_title = normalize_title(title)
        loc = parse_location(item.location_raw)
        remote_type = (
            item.remote_hint
            if item.remote_hint in {"remote", "hybrid", "onsite", "unknown"}
            else loc["remote_type"]
        )
        seniority = parse_seniority(title, item.description)
        cls = classify(title, item.description, item.department, seniority)
        bucket = dedupe_bucket(slugify(company.name), loc["country"])

        salary_min = item.salary_min
        salary_max = item.salary_max
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min
            log.warning(
                "posting.salary_bounds_swapped",
                board_id=board.id,
                external_id=external_id,
            )

        # first_seen_at is always the observation time. Bulk imports are marked
        # separately and scored down rather than falsifying the observation date.
        chash = content_hash(
            title,
            item.description,
            item.location_raw,
            item.department,
            item.employment_type,
            item.remote_hint,
            str(salary_min),
            str(salary_max),
            item.salary_currency,
            item.apply_url,
        )
        row = JobPosting(
            board_id=board.id,
            company_id=board.company_id,
            external_id=external_id,
            title=truncate(title, 400) or "Untitled",
            normalized_title=norm_title[:400],
            description=sanitize_description(item.description),
            department=truncate(clean_text(item.department), 200),
            employment_type=truncate(clean_text(item.employment_type), 60),
            seniority=seniority,
            role_family=cls.role_family,
            role_family_confidence=cls.confidence,
            classification_evidence=cls.evidence,
            skills=cls.skills,
            location_raw=truncate(clean_text(item.location_raw), 300),
            city=truncate(loc["city"], 120),
            region=truncate(loc["region"], 120),
            country=loc["country"],
            remote_type=remote_type,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=clean_text(item.salary_currency).upper()[:3] or None,
            url=truncate(canonical_url(item.url), 1000) or "",
            apply_url=truncate(canonical_url(item.apply_url), 1000),
            posted_at=item.posted_at,
            updated_at_source=item.updated_at,
            first_seen_at=now,
            last_seen_at=now,
            missed_scans=0,
            is_active=True,
            is_bulk_import=result.bulk_sync,
            content_hash=chash,
            dedupe_key=dedupe_key(slugify(company.name), norm_title, loc["country"]),
            dedupe_bucket=bucket,
            raw=sanitize_raw(item.raw if isinstance(item.raw, dict) else {}),
        )

        near = best_fuzzy_match(
            by_bucket.get(bucket, []),
            norm_title,
            s.dedupe_threshold,
        )
        if near is not None:
            near.last_seen_at = now
            near.missed_scans = 0
            near.is_active = True
            row.is_active = False
            row.repost_of_id = near.id
            result.deduped += 1
            POSTINGS_DEDUPED.inc()
        else:
            repost = best_fuzzy_match(
                inactive_by_bucket.get(bucket, []),
                norm_title,
                s.repost_threshold,
            )
            if repost is not None:
                row.repost_of_id = repost.id
                result.reposts += 1

        session.add(row)
        result.created += 1
        POSTINGS_CREATED.inc()
        existing_by_external[external_id] = row
        # Do not let an already-folded duplicate become the candidate for
        # subsequent jobs in the same provider response.
        if row.is_active:
            by_bucket[bucket].append(row)
        if cls.confidence < s.low_confidence_threshold:
            new_reviews.append((row, cls))

    # Make sure IDs exist before creating foreign-key review rows.
    await session.flush()
    for row, cls in new_reviews:
        await _insert_review(session, row, cls)

    # Only a successful non-empty response is evidence that a missing posting
    # disappeared. The UPDATE is RETURNING, so the metric counts actual closures.
    missing = [external_id for external_id in existing_by_external if external_id not in seen_ids]
    if missing:
        stmt = (
            update(JobPosting)
            .where(
                JobPosting.board_id == board.id,
                JobPosting.external_id.in_(missing),
                JobPosting.is_active.is_(True),
            )
            .values(
                missed_scans=JobPosting.missed_scans + 1,
                is_active=JobPosting.missed_scans + 1 >= s.inactive_after_misses,
            )
            .returning(JobPosting.id)
        )
        closed_ids = list((await session.execute(stmt)).scalars())
        result.deactivated = len(closed_ids)
        if closed_ids:
            POSTINGS_DEACTIVATED.inc(len(closed_ids))

    await _refresh_company_aggregates(session, board.company_id)

    run.status = "ok"
    _finish_run(run, started, result)
    BOARDS_SCANNED.labels(board.provider, "ok").inc()
    INGEST_DURATION.labels(board.provider).observe(time.perf_counter() - started)
    return result


def _finish_run(run: IngestionRun, started: float, result: BoardResult) -> None:
    run.finished_at = utcnow()
    run.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    run.fetched = result.fetched
    run.created = result.created
    run.updated = result.updated
    run.deduped = result.deduped
    run.deactivated = result.deactivated
    run.metadata_json = {
        "provider": result.provider,
        "token": result.token,
        "bulk_sync": result.bulk_sync,
        "empty_response": result.empty_response,
        "reposts": result.reposts,
    }


async def _refresh_company_aggregates(session: AsyncSession, company_id: int) -> None:
    total = (
        await session.execute(
            select(func.count())
            .select_from(JobPosting)
            .where(
                JobPosting.company_id == company_id,
                JobPosting.is_active.is_(True),
            )
        )
    ).scalar_one()
    company = await session.get(Company, company_id)
    if company is None:
        return

    inferred = infer_open_roles_band(total)
    if inferred and company.headcount_band != inferred:
        company.headcount_band = inferred



async def run_board(
    session: AsyncSession,
    board_id: int,
    client: HttpClient,
) -> BoardResult:
    board = await session.get(JobBoard, board_id)
    if board is None:
        return BoardResult(
            board_id=board_id,
            provider="?",
            token="?",
            error="board_not_found",
        )
    return await ingest_board(session, board, client)


async def run_all(
    session_factory,
    client: HttpClient,
    *,
    provider: str | None = None,
    limit: int | None = None,
    concurrency: int = 8,
) -> list[BoardResult]:
    """Run active boards with independent transactions and bounded concurrency."""
    async with session_factory() as discovery_session:
        query = select(JobBoard.id).where(JobBoard.is_active.is_(True))
        if provider:
            query = query.where(JobBoard.provider == provider)
        if limit is not None:
            query = query.limit(limit)
        board_ids = list((await discovery_session.execute(query)).scalars())
    ACTIVE_BOARDS.set(len(board_ids))

    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[BoardResult] = []

    async def one(board_id: int) -> None:
        async with sem:
            try:
                async with session_factory() as db_session:
                    result = await run_board(db_session, board_id, client)
                    await db_session.commit()
                results.append(result)
            except Exception as exc:
                log.exception("board.transaction_failed", board_id=board_id, error=str(exc))
                results.append(
                    BoardResult(
                        board_id=board_id,
                        provider="?",
                        token="?",
                        error=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                )

    await asyncio.gather(*(one(board_id) for board_id in board_ids))
    results.sort(key=lambda result: result.board_id)
    return results


def summarize(results: list[BoardResult]) -> dict[str, int]:
    return {
        "boards": len(results),
        "boards_ok": sum(result.error is None for result in results),
        "boards_failed": sum(result.error is not None for result in results),
        "fetched": sum(result.fetched for result in results),
        "created": sum(result.created for result in results),
        "updated": sum(result.updated for result in results),
        "unchanged": sum(result.unchanged for result in results),
        "deduped": sum(result.deduped for result in results),
        "reposts": sum(result.reposts for result in results),
        "deactivated": sum(result.deactivated for result in results),
        "bulk_syncs": sum(result.bulk_sync for result in results),
        "empty_responses": sum(result.empty_response for result in results),
    }
