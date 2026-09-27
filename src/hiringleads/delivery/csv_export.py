from __future__ import annotations

import csv
import datetime as dt
import io

from ..matching import Lead

COLUMNS = [
    "score",
    "company",
    "domain",
    "open_roles_band",
    "title",
    "role_family",
    "seniority",
    "skills",
    "match_evidence",
    "city",
    "region",
    "country",
    "remote_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "posted_at",
    "first_seen_at",
    "open_roles_30d",
    "open_roles_total",
    "is_repost",
    "job_url",
    "apply_url",
    "contact_page",
    "linkedin_search",
]


def leads_to_csv(leads: list[Lead]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()

    for lead in leads:
        writer.writerow(
            {
                "score": lead.score,
                "company": lead.company,
                "domain": lead.domain or "",
                "open_roles_band": lead.open_roles_band or "",
                "title": lead.title,
                "role_family": lead.role_family or "",
                "seniority": lead.seniority or "",
                "skills": ", ".join(lead.skills),
                "match_evidence": " · ".join(lead.evidence),
                "city": lead.city or "",
                "region": lead.region or "",
                "country": lead.country or "",
                "remote_type": lead.remote_type or "",
                "salary_min": "" if lead.salary_min is None else lead.salary_min,
                "salary_max": "" if lead.salary_max is None else lead.salary_max,
                "salary_currency": lead.salary_currency or "",
                "posted_at": lead.posted_at.isoformat() if lead.posted_at else "",
                "first_seen_at": lead.first_seen_at.isoformat(),
                "open_roles_30d": lead.open_roles_30d,
                "open_roles_total": lead.open_roles_total,
                "is_repost": "yes" if lead.is_repost else "",
                "job_url": lead.url,
                "apply_url": lead.apply_url or "",
                "contact_page": lead.contact_page or "",
                "linkedin_search": lead.linkedin_search,
            }
        )
    return buffer.getvalue()


def leads_to_csv_bytes(leads: list[Lead]) -> bytes:
    return ("\ufeff" + leads_to_csv(leads)).encode("utf-8")


def default_filename(
    watchlist_name: str,
    now: dt.datetime | None = None,
) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    safe = "".join(
        char if char.isalnum() or char in "-_" else "-"
        for char in watchlist_name.casefold()
    ).strip("-")
    return f"leads-{safe or 'watchlist'}-{now:%Y%m%d}.csv"
