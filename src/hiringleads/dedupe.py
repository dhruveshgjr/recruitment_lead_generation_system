"""Exact, near-duplicate and repost detection.

The ingestion hot path should never execute one SQL fuzzy-search per posting.
Callers should preload recent postings and use ``best_fuzzy_match`` in memory.
The async helpers remain available for one-off jobs and tests.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import JobPosting


def best_fuzzy_match(
    candidates: list[JobPosting],
    normalized_title: str,
    threshold: int,
) -> JobPosting | None:
    best: tuple[float, JobPosting] | None = None
    for candidate in candidates:
        ratio = fuzz.token_set_ratio(normalized_title, candidate.normalized_title)
        if ratio >= threshold and (best is None or ratio > best[0]):
            best = (ratio, candidate)
    return best[1] if best else None


def build_bucket_index(postings: list[JobPosting]) -> dict[str, list[JobPosting]]:
    index: dict[str, list[JobPosting]] = defaultdict(list)
    for posting in postings:
        index[posting.dedupe_bucket].append(posting)
    return dict(index)


async def find_near_duplicate(
    session: AsyncSession,
    *,
    company_id: int,
    bucket: str,
    normalized_title: str,
    exclude_id: int | None = None,
    now: dt.datetime | None = None,
) -> JobPosting | None:
    """One-off DB helper; production ingestion uses a preloaded index."""
    s = settings()
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=s.dedupe_window_days)

    q = select(JobPosting).where(
        JobPosting.company_id == company_id,
        JobPosting.dedupe_bucket == bucket,
        JobPosting.last_seen_at >= cutoff,
    )
    if exclude_id:
        q = q.where(JobPosting.id != exclude_id)

    return best_fuzzy_match(
        list((await session.execute(q)).scalars()),
        normalized_title,
        s.dedupe_threshold,
    )


async def find_repost(
    session: AsyncSession,
    *,
    company_id: int,
    bucket: str,
    normalized_title: str,
    now: dt.datetime | None = None,
) -> JobPosting | None:
    s = settings()
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=s.repost_window_days)

    candidates = list(
        (
            await session.execute(
                select(JobPosting)
                .where(
                    JobPosting.company_id == company_id,
                    JobPosting.dedupe_bucket == bucket,
                    JobPosting.is_active.is_(False),
                    JobPosting.last_seen_at >= cutoff,
                )
                .order_by(JobPosting.last_seen_at.desc())
                .limit(250)
            )
        ).scalars()
    )
    return best_fuzzy_match(candidates, normalized_title, s.repost_threshold)
