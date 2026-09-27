from hiringleads.delivery.csv_export import leads_to_csv
from hiringleads.matching import Lead


def test_csv_contains_company_hiring_band():
    lead = Lead(
        job_id=1,
        company_id=2,
        company="Acme",
        domain="acme.com",
        open_roles_band="201-500",
        title="Backend Engineer",
        role_family="backend",
        skills=["python"],
        seniority="senior",
        city="Austin",
        region="TX",
        country="US",
        remote_type="hybrid",
        salary_min=100000,
        salary_max=150000,
        salary_currency="USD",
        url="https://acme.example/job",
        apply_url=None,
        posted_at=None,
        first_seen_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
        score=90,
        components={},
        evidence=["title:Backend"],
        open_roles_30d=12,
        open_roles_total=40,
        is_repost=False,
        contact_page="https://acme.com/careers",
        linkedin_search="https://linkedin.com/search",
    )
    csv = leads_to_csv([lead])
    assert "open_roles_band" in csv
    assert "201-500" in csv
