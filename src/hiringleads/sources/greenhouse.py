from __future__ import annotations

import re

from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting

_HTML = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</(?:p|div|li|h[1-6]|tr)>", re.I)


def html_to_text(html: str | None) -> str | None:
    """Greenhouse and Lever both return HTML-escaped job descriptions.

    We keep a plain-text copy for classification. We deliberately do NOT store
    the raw HTML for display — we link out to the original posting instead.
    """
    if not html:
        return None
    import html as html_mod

    s = _BLOCK.sub("\n", html)
    s = _HTML.sub(" ", s)
    s = html_mod.unescape(s)
    s = clean_text(s.replace("\n", " "))
    return s or None


class GreenhouseSource(JobSource):
    provider = "greenhouse"
    BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    async def fetch(self, token: str) -> list[RawPosting]:
        url = self.BASE.format(token=token)
        data = await self.client.get_json(url, content="true")
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        out: list[RawPosting] = []

        for j in jobs:
            loc = (j.get("location") or {}).get("name")
            offices = ", ".join(o.get("name", "") for o in (j.get("offices") or []) if o.get("name"))
            dept = ", ".join(d.get("name", "") for d in (j.get("departments") or []) if d.get("name"))
            meta = {m.get("name", "").lower(): m.get("value") for m in (j.get("metadata") or []) if m}

            out.append(
                RawPosting(
                    external_id=str(j.get("id")),
                    title=clean_text(j.get("title")),
                    url=j.get("absolute_url") or f"https://boards.greenhouse.io/{token}",
                    description=html_to_text(j.get("content")),
                    location_raw=clean_text(loc or offices) or None,
                    department=clean_text(dept) or None,
                    employment_type=meta.get("employment type"),
                    posted_at=parse_datetime(j.get("first_published") or j.get("updated_at")),
                    updated_at=parse_datetime(j.get("updated_at")),
                    company_name=clean_text(j.get("company_name")) or None,
                    raw={k: v for k, v in j.items() if k != "content"},
                )
            )
        return out
