from __future__ import annotations

from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting
from .greenhouse import html_to_text


class RecruiteeSource(JobSource):
    provider = "recruitee"
    BASE = "https://{token}.recruitee.com/api/offers/"

    async def fetch(self, token: str) -> list[RawPosting]:
        data = await self.client.get_json(self.BASE.format(token=token))
        offers = data.get("offers", []) if isinstance(data, dict) else []
        out: list[RawPosting] = []

        for j in offers:
            if j.get("status") and j["status"] != "published":
                continue
            sal = j.get("salary") or {}
            remote_hint = "remote" if j.get("remote") else ("hybrid" if j.get("hybrid") else None)
            out.append(
                RawPosting(
                    external_id=str(j.get("id")),
                    title=clean_text(j.get("title")),
                    url=j.get("careers_url") or f"https://{token}.recruitee.com",
                    apply_url=j.get("careers_apply_url"),
                    description=html_to_text(j.get("description")) or None,
                    location_raw=clean_text(j.get("location")) or None,
                    department=clean_text(j.get("department")) or None,
                    employment_type=clean_text(j.get("employment_type_code")) or None,
                    remote_hint=remote_hint,
                    posted_at=parse_datetime(j.get("created_at")),
                    updated_at=parse_datetime(j.get("updated_at")),
                    salary_min=sal.get("min"),
                    salary_max=sal.get("max"),
                    salary_currency=sal.get("currency"),
                    company_name=clean_text(j.get("company_name")) or None,
                    raw=j,
                )
            )
        return out
