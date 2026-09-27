from __future__ import annotations

from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting


class SmartRecruitersSource(JobSource):
    provider = "smartrecruiters"
    BASE = "https://api.smartrecruiters.com/v1/companies/{token}/postings"

    async def fetch(self, token: str) -> list[RawPosting]:
        out: list[RawPosting] = []
        offset = 0
        limit = 100

        while True:
            data = await self.client.get_json(
                self.BASE.format(token=token), limit=limit, offset=offset
            )
            if not isinstance(data, dict):
                break
            content = data.get("content", [])
            if not content:
                break

            for j in content:
                loc = j.get("location") or {}
                loc_str = ", ".join(
                    filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])
                )
                out.append(
                    RawPosting(
                        external_id=str(j.get("id")),
                        title=clean_text(j.get("name")),
                        url=f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}",
                        location_raw=clean_text(loc_str) or None,
                        department=clean_text(j.get("department")) or None,
                        employment_type=clean_text(j.get("typeOfEmployment")) or None,
                        remote_hint="remote" if loc.get("remote") else None,
                        posted_at=parse_datetime(j.get("releasedDate")),
                        company_name=clean_text((j.get("company") or {}).get("name")) or None,
                        raw=j,
                    )
                )

            total = data.get("totalFound", 0)
            offset += limit
            if offset >= total:
                break

        return out
