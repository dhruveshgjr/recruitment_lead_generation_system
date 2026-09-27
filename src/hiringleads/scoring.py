"""Explainable lead scoring: 0..100, deterministic and testable."""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from .taxonomy import SENIORITY_ORDER

WEIGHTS = {
    "freshness": 0.30,
    "relevance": 0.35,
    "fit": 0.15,
    "velocity": 0.15,
    "quality": 0.05,
}


@dataclass(slots=True)
class ScoreInputs:
    first_seen_at: dt.datetime
    role_family: str | None
    role_family_confidence: float
    skills: list[str]
    seniority: str | None
    country: str | None
    region: str | None
    remote_type: str | None
    salary_min: float | None
    salary_max: float | None
    description_len: int
    apply_url: str | None
    company_open_roles_30d: int
    company_open_roles_total: int
    is_bulk_import: bool = False
    is_repost: bool = False


@dataclass(slots=True)
class WatchlistSpec:
    role_families: list[str]
    skills: list[str]
    exclude_skills: list[str]
    seniorities: list[str]
    countries: list[str]
    regions: list[str]
    remote_ok: bool
    include_keywords: list[str]
    exclude_keywords: list[str]


def _freshness(
    first_seen_at: dt.datetime,
    now: dt.datetime,
    *,
    half_life_days: float = 4.0,
    bulk_import: bool = False,
) -> float:
    age_days = max(0.0, (now - first_seen_at).total_seconds() / 86400.0)
    value = math.exp(-age_days * math.log(2) / half_life_days)
    # Imported historical rows remain real observations, but should not become
    # indistinguishable from a newly observed role simply because the first scan
    # occurred today.
    return value * 0.25 if bulk_import else value


def _relevance(job: ScoreInputs, wl: WatchlistSpec) -> float:
    score_value = 0.0
    if wl.role_families and job.role_family in wl.role_families:
        score_value += 0.45

    if wl.skills:
        overlap = len(set(wl.skills) & set(job.skills))
        target = max(1, min(len(wl.skills), 3))
        score_value += 0.45 * min(1.0, overlap / target)

    if wl.seniorities and job.seniority:
        if job.seniority in wl.seniorities:
            score_value += 0.10
        else:
            positions = [
                SENIORITY_ORDER.index(value)
                for value in wl.seniorities
                if value in SENIORITY_ORDER
            ]
            if positions and job.seniority in SENIORITY_ORDER:
                distance = min(
                    abs(SENIORITY_ORDER.index(job.seniority) - position)
                    for position in positions
                )
                score_value += 0.10 * max(0.0, 1.0 - distance / 3.0)

    return min(1.0, score_value)


def _company_fit(job: ScoreInputs, wl: WatchlistSpec) -> float:
    value = 0.50

    if wl.countries:
        if job.country and job.country in wl.countries:
            value += 0.30
        elif job.remote_type == "remote" and wl.remote_ok:
            value += 0.15
        elif job.country:
            value -= 0.25

    if wl.regions:
        if job.region and job.region in wl.regions:
            value += 0.20
        elif job.region:
            value -= 0.10

    return max(0.0, min(1.0, value))


def _velocity(job: ScoreInputs) -> float:
    if job.company_open_roles_30d <= 0:
        return 0.0
    return min(1.0, math.log1p(job.company_open_roles_30d) / math.log1p(40))


def _quality(job: ScoreInputs) -> float:
    value = 0.0
    value += 0.30 if job.description_len > 400 else (0.15 if job.description_len > 100 else 0.0)
    value += 0.20 if job.country else 0.0
    value += 0.15 if job.apply_url else 0.0
    value += 0.15 if job.salary_min is not None or job.salary_max is not None else 0.0
    value += 0.10 if job.role_family and job.role_family != "other" else 0.0
    value += 0.10 * min(1.0, max(0.0, job.role_family_confidence))
    value += 0.10 if job.remote_type and job.remote_type != "unknown" else 0.0
    return min(1.0, value)


def _norm_set(values: list[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


def passes_hard_filters(
    job: ScoreInputs,
    wl: WatchlistSpec,
    title: str,
    now: dt.datetime,
) -> bool:
    title_l = title.casefold()

    if wl.exclude_skills and _norm_set(wl.exclude_skills) & _norm_set(job.skills):
        return False
    if wl.exclude_keywords and any(keyword.casefold() in title_l for keyword in wl.exclude_keywords):
        return False
    if wl.include_keywords and not any(keyword.casefold() in title_l for keyword in wl.include_keywords):
        return False
    if wl.role_families and job.role_family not in wl.role_families:
        return False
    if wl.seniorities and job.seniority not in wl.seniorities:
        return False
    if wl.countries and not (
        job.country in wl.countries
        or (wl.remote_ok and job.remote_type == "remote")
    ):
        return False
    if wl.regions and job.region not in wl.regions:
        return False
    if not wl.remote_ok and job.remote_type == "remote":
        return False

    # ``now`` is retained in the signature so callers can keep filters/scoring
    # contracts uniform; age is already constrained in the SQL query.
    _ = now
    return True


def score(
    job: ScoreInputs,
    wl: WatchlistSpec,
    now: dt.datetime | None = None,
) -> tuple[float, dict[str, float]]:
    now = now or dt.datetime.now(dt.timezone.utc)
    components = {
        "freshness": _freshness(
            job.first_seen_at,
            now,
            bulk_import=job.is_bulk_import,
        ),
        "relevance": _relevance(job, wl),
        "fit": _company_fit(job, wl),
        "velocity": _velocity(job),
        "quality": _quality(job),
    }
    total = sum(WEIGHTS[key] * value for key, value in components.items()) * 100.0

    # Reposts are intentionally visible as signals rather than being deleted.
    # Their score gets a modest, bounded lift.
    if job.is_repost:
        total = min(100.0, total + 5.0)

    return round(total, 2), {key: round(value, 3) for key, value in components.items()}
