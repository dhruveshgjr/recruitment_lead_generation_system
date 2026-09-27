import datetime as dt

from hiringleads.scoring import ScoreInputs, WatchlistSpec, passes_hard_filters, score


NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def job(**overrides):
    data = dict(
        first_seen_at=NOW,
        role_family="backend",
        role_family_confidence=0.9,
        skills=["rust"],
        seniority="senior",
        country="US",
        region="CA",
        remote_type="remote",
        salary_min=150000,
        salary_max=220000,
        description_len=1200,
        apply_url="https://example.com/apply",
        company_open_roles_30d=20,
        company_open_roles_total=60,
        is_bulk_import=False,
        is_repost=False,
    )
    data.update(overrides)
    return ScoreInputs(**data)


def wl(**overrides):
    data = dict(
        role_families=["backend"],
        skills=["rust"],
        exclude_skills=[],
        seniorities=["senior"],
        countries=["US"],
        regions=["CA"],
        remote_ok=True,
        include_keywords=[],
        exclude_keywords=[],
    )
    data.update(overrides)
    return WatchlistSpec(**data)


def test_one_skill_watchlist_gets_full_skill_component():
    value, parts = score(job(), wl(), NOW)
    assert parts["relevance"] >= 0.55
    assert value > 0


def test_excluded_skill_is_hard_filtered():
    assert not passes_hard_filters(job(skills=["rust", "java"]), wl(exclude_skills=["java"]), "Senior Backend Engineer", NOW)


def test_bulk_import_is_penalized_but_not_backdated():
    normal, _ = score(job(), wl(), NOW)
    imported, _ = score(job(is_bulk_import=True), wl(), NOW)
    assert imported < normal


def test_repost_lift_is_bounded():
    base, _ = score(job(), wl(), NOW)
    repost, _ = score(job(is_repost=True), wl(), NOW)
    assert repost == min(100.0, base + 5.0)


def test_unknown_seniority_is_rejected_when_requested():
    assert not passes_hard_filters(job(seniority=None), wl(), "Backend Engineer", NOW)


def test_unknown_country_is_rejected_when_requested():
    assert not passes_hard_filters(job(country=None, remote_type="unknown"), wl(), "Backend Engineer", NOW)
