"""Watchlist -> recruiter leads."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .enrich.company import contact_page_url, linkedin_company_search_url
from .models import Company, DeliveredLead, JobPosting, Watchlist
from .observability import MATCH_SCAN_CAP_HITS
from .scoring import (
    ScoreInputs,
    WatchlistSpec,
    passes_hard_filters,
    score,
)


@dataclass(slots=True)
class Lead:
    job_id: int
    company_id: int
    company: str
    domain: str | None
    open_roles_band: str | None
    title: str
    role_family: str | None
    skills: list[str]
    seniority: str | None
    city: str | None
    region: str | None
    country: str | None
    remote_type: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    url: str
    apply_url: str | None
    posted_at: dt.datetime | None
    first_seen_at: dt.datetime
    score: float
    components: dict[str, float]
    evidence: list[str]
    open_roles_30d: int
    open_roles_total: int
    is_repost: bool
    contact_page: str | None
    linkedin_search: str


def _spec(wl: Watchlist) -> WatchlistSpec:
    normalize = lambda values: [str(v).strip().casefold() for v in (values or []) if str(v).strip()]
    return WatchlistSpec(
        role_families=normalize(wl.role_families),
        skills=normalize(wl.skills),
        exclude_skills=normalize(wl.exclude_skills),
        seniorities=normalize(wl.seniorities),
        countries=[str(v).strip().upper() for v in (wl.countries or []) if str(v).strip()],
        regions=[str(v).strip().upper() for v in (wl.regions or []) if str(v).strip()],
        remote_ok=bool(wl.remote_ok),
        include_keywords=normalize(wl.include_keywords),
        exclude_keywords=normalize(wl.exclude_keywords),
    )


async def _company_velocity(
    session: AsyncSession,
    company_ids: list[int],
    now: dt.datetime,
) -> dict[int, tuple[int, int]]:
    if not company_ids:
        return {}

    since = now - dt.timedelta(days=30)
    rows = (
        await session.execute(
            select(
                JobPosting.company_id,
                func.count().filter(
                    (JobPosting.first_seen_at >= since) & JobPosting.is_bulk_import.is_(False)
                ).label("recent"),
                func.count().label("total"),
            )
            .where(
                JobPosting.company_id.in_(company_ids),
                JobPosting.is_active.is_(True),
            )
            .group_by(JobPosting.company_id)
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def _apply_keyword_filters(query, wl_spec: WatchlistSpec):
    if wl_spec.include_keywords:
        query = query.where(
            or_(
                *[
                    JobPosting.title.ilike(f"%{keyword}%")
                    for keyword in wl_spec.include_keywords
                ]
            )
        )
    if wl_spec.exclude_keywords:
        query = query.where(
            not_(
                or_(
                    *[
                        JobPosting.title.ilike(f"%{keyword}%")
                        for keyword in wl_spec.exclude_keywords
                    ]
                )
            )
        )
    return query


async def build_leads(
    session: AsyncSession,
    watchlist: Watchlist,
    *,
    since: dt.datetime | None = None,
    exclude_delivered: bool = True,
    limit: int | None = None,
    now: dt.datetime | None = None,
) -> list[Lead]:
    """Build scored leads with filters pushed into SQL as far as practical."""
    now = now or dt.datetime.now(dt.timezone.utc)
    wl_spec = _spec(watchlist)
    requested_since = since or watchlist.last_delivered_at or (
        now - dt.timedelta(days=watchlist.max_age_days)
    )
    age_floor = now - dt.timedelta(days=watchlist.max_age_days)
    oldest = max(requested_since, age_floor)

    scan_cap = settings().match_scan_cap
    q = (
        select(JobPosting)
        .where(
            JobPosting.is_active.is_(True),
            JobPosting.first_seen_at >= oldest,
        )
        .order_by(JobPosting.first_seen_at.desc(), JobPosting.id.desc())
        .limit(scan_cap + 1)
    )

    if wl_spec.role_families:
        q = q.where(JobPosting.role_family.in_(wl_spec.role_families))
    if wl_spec.skills:
        q = q.where(JobPosting.skills.overlap(wl_spec.skills))
    if wl_spec.exclude_skills:
        q = q.where(not_(JobPosting.skills.overlap(wl_spec.exclude_skills)))
    if wl_spec.seniorities:
        q = q.where(JobPosting.seniority.in_(wl_spec.seniorities))
    if wl_spec.countries:
        q = q.where(
            or_(
                JobPosting.country.in_(wl_spec.countries),
                (JobPosting.remote_type == "remote") & watchlist.remote_ok,
            )
        )
    if wl_spec.regions:
        q = q.where(JobPosting.region.in_(wl_spec.regions))
    if not watchlist.remote_ok:
        q = q.where(JobPosting.remote_type != "remote")
    q = _apply_keyword_filters(q, wl_spec)

    if exclude_delivered:
        delivered_exists = exists(
            select(DeliveredLead.id).where(
                DeliveredLead.watchlist_id == watchlist.id,
                DeliveredLead.job_id == JobPosting.id,
            )
        )
        q = q.where(not_(delivered_exists))

    jobs = list((await session.execute(q)).scalars())
    if len(jobs) > scan_cap:
        jobs = jobs[:scan_cap]
        MATCH_SCAN_CAP_HITS.inc()
        import structlog
        structlog.get_logger().warning(
            "match.scan_cap_reached",
            watchlist_id=watchlist.id,
            scan_cap=scan_cap,
            age_days=watchlist.max_age_days,
        )
    if not jobs:
        return []

    company_ids = list({job.company_id for job in jobs})
    companies = {
        company.id: company
        for company in (
            await session.execute(
                select(Company).where(Company.id.in_(company_ids))
            )
        ).scalars()
    }
    velocity = await _company_velocity(session, company_ids, now)

    leads: list[Lead] = []
    for job in jobs:
        company = companies.get(job.company_id)
        if company is None:
            continue

        recent, total = velocity.get(company.id, (0, 0))
        inputs = ScoreInputs(
            first_seen_at=job.first_seen_at,
            role_family=job.role_family,
            role_family_confidence=job.role_family_confidence,
            skills=[str(skill).casefold() for skill in (job.skills or [])],
            seniority=job.seniority.casefold() if job.seniority else None,
            country=job.country,
            region=job.region,
            remote_type=job.remote_type,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            description_len=len(job.description or ""),
            apply_url=job.apply_url,
            company_open_roles_30d=recent,
            company_open_roles_total=total,
            is_bulk_import=job.is_bulk_import,
            is_repost=job.repost_of_id is not None,
        )
        if not passes_hard_filters(inputs, wl_spec, job.title, now):
            continue

        lead_score, components = score(inputs, wl_spec, now)
        if lead_score < watchlist.min_score:
            continue

        leads.append(
            Lead(
                job_id=job.id,
                company_id=company.id,
                company=company.name,
                domain=company.domain,
                open_roles_band=company.open_roles_band,
                title=job.title,
                role_family=job.role_family,
                skills=list(job.skills or [])[:8],
                seniority=job.seniority,
                city=job.city,
                region=job.region,
                country=job.country,
                remote_type=job.remote_type,
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                salary_currency=job.salary_currency,
                url=job.url,
                apply_url=job.apply_url,
                posted_at=job.posted_at,
                first_seen_at=job.first_seen_at,
                score=lead_score,
                components=components,
                evidence=list(job.classification_evidence or []),
                open_roles_30d=recent,
                open_roles_total=total,
                is_repost=job.repost_of_id is not None,
                contact_page=contact_page_url(company.domain),
                linkedin_search=linkedin_company_search_url(company.name),
            )
        )

    leads.sort(key=lambda lead: (-lead.score, -lead.open_roles_30d, lead.company.casefold(), lead.job_id))
    cap = limit if limit is not None else watchlist.daily_cap
    return leads[: max(0, cap)]


async def mark_delivered(
    session: AsyncSession,
    watchlist_id: int,
    leads: list[Lead],
) -> None:
    """Idempotently watermark a successful email delivery."""
    if not leads:
        return

    now = dt.datetime.now(dt.timezone.utc)
    stmt = (
        pg_insert(DeliveredLead)
        .values(
            [
                {
                    "watchlist_id": watchlist_id,
                    "job_id": lead.job_id,
                    "score": lead.score,
                    "delivered_at": now,
                }
                for lead in leads
            ]
        )
        .on_conflict_do_nothing(index_elements=["watchlist_id", "job_id"])
    )
    await session.execute(stmt)

    wl = await session.get(Watchlist, watchlist_id)
    if wl:
        wl.last_delivered_at = now
    await session.flush()
