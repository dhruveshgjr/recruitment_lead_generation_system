"""Minimal company-level enrichment.

No people-search, contact harvesting, or employee PII. Company-level signals
are enough for the recruiting BD workflow.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

from ..taxonomy import HEADCOUNT_BANDS

_ATS_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
    "jobs.smartrecruiters.com",
    "news.ycombinator.com",
    "api.lever.co",
    "boards-api.greenhouse.io",
    "api.ashbyhq.com",
    "api.smartrecruiters.com",
}
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", re.IGNORECASE)


def registrable_domain(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None

    if not host or host in _ATS_HOSTS:
        return None
    if host.endswith(".recruitee.com") or host.endswith(".greenhouse.io"):
        return None
    if not _DOMAIN_RE.fullmatch(host):
        return None

    parts = host.split(".")
    # Without tldextract we avoid pretending every multi-part public suffix is
    # perfectly modeled. This removes common site prefixes and keeps the rest.
    if len(parts) > 2 and parts[0] in {"www", "careers", "jobs", "apply"}:
        host = ".".join(parts[1:])
    return host


def infer_open_roles_band(open_roles: int) -> str | None:
    if open_roles <= 0:
        return None
    if open_roles < 5:
        return "11-50"
    if open_roles < 15:
        return "51-200"
    if open_roles < 40:
        return "201-500"
    if open_roles < 100:
        return "501-1000"
    if open_roles < 300:
        return "1001-5000"
    return "5000+"


def contact_page_url(domain: str | None) -> str | None:
    return f"https://{domain}/careers" if domain else None


def linkedin_company_search_url(company_name: str) -> str:
    return (
        "https://www.linkedin.com/search/results/companies/"
        f"?keywords={quote_plus(company_name)}"
    )
