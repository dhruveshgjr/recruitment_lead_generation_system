"""Curated seed boards.

Start here. A few hundred hand-verified boards gets you a real product on day
one. Common Crawl scales you to tens of thousands on day thirty.

The token is the ATS-specific board identifier, NOT the company name.
Verify each one with `hl discover probe <domain>` before adding.
"""
from __future__ import annotations

from .probe import DiscoveredBoard

# (provider, token)
SEED_BOARDS: list[tuple[str, str]] = [
    # --- large tech, high posting volume, always-on hiring ---
    ("greenhouse", "stripe"),
    ("greenhouse", "databricks"),
    ("greenhouse", "doordash"),
    ("greenhouse", "robinhood"),
    ("greenhouse", "coinbase"),
    ("greenhouse", "airtable"),
    ("greenhouse", "benchling"),
    ("greenhouse", "discord"),
    ("greenhouse", "figma"),
    ("greenhouse", "gitlab"),
    ("greenhouse", "hashicorp"),
    ("greenhouse", "instacart"),
    ("greenhouse", "lyft"),
    ("greenhouse", "pinterest"),
    ("greenhouse", "reddit"),
    ("greenhouse", "samsara"),
    ("greenhouse", "segment"),
    ("greenhouse", "squarespace"),
    ("greenhouse", "twilio"),
    ("greenhouse", "wayfair"),
    ("greenhouse", "zapier"),
    ("greenhouse", "elastic"),
    ("greenhouse", "confluent"),
    ("greenhouse", "mongodb"),
    ("greenhouse", "datadog"),
    ("greenhouse", "cloudflare"),
    ("greenhouse", "anthropic"),
    ("greenhouse", "openai"),

    # --- lever ---
    ("lever", "netflix"),
    ("lever", "spotify"),
    ("lever", "shopify"),
    ("lever", "kraken"),
    ("lever", "plaid"),
    ("lever", "brex"),
    ("lever", "ramp"),
    ("lever", "rippling"),
    ("lever", "attentive"),
    ("lever", "nuro"),
    ("lever", "scaleai"),

    # --- ashby ---
    ("ashby", "linear"),
    ("ashby", "vercel"),
    ("ashby", "supabase"),
    ("ashby", "neon"),
    ("ashby", "clerk"),
    ("ashby", "resend"),
    ("ashby", "modal"),
    ("ashby", "baseten"),

    # --- workable ---
    ("workable", "bettercloud"),
    ("workable", "trustpilot"),

    # --- smartrecruiters ---
    ("smartrecruiters", "Visa"),
    ("smartrecruiters", "Bosch"),
    ("smartrecruiters", "McDonalds"),

    # --- non-ATS, always-on ---
    ("hn_whoishiring", "latest"),
]


def seed_boards() -> list[DiscoveredBoard]:
    out: list[DiscoveredBoard] = []
    for provider, token in SEED_BOARDS:
        if provider == "hn_whoishiring":
            url = "https://news.ycombinator.com/"
        elif provider == "greenhouse":
            url = f"https://boards.greenhouse.io/{token}"
        elif provider == "lever":
            url = f"https://jobs.lever.co/{token}"
        elif provider == "ashby":
            url = f"https://jobs.ashbyhq.com/{token}"
        elif provider == "workable":
            url = f"https://apply.workable.com/{token}/"
        elif provider == "smartrecruiters":
            url = f"https://jobs.smartrecruiters.com/{token}"
        else:
            url = ""
        out.append(
            DiscoveredBoard(
                provider=provider,
                token=token,
                url=url,
                company_name=token.replace("-", " ").title(),
                discovered_via="seed",
            )
        )
    return out
