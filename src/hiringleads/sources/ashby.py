from __future__ import annotations

from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting


class AshbySource(JobSource):
    provider = "ashby"
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{token}"

    async def fetch(self, token: str) -> list[RawPosting]:
        data = await self.client.get_json(
            self.BASE.format(token=token), includeCompensation="true"
        )
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        out: list[RawPosting] = []

        for j in jobs:
            if j.get("isListed") is False:
                continue
            comp = j.get("compensation") or {}
            summary = comp.get("compensationTierSummary") or {}
            locs = [j.get("location")] + [s.get("location") for s in (j.get("secondaryLocations") or [])]
            loc_str = ", ".join(filter(None, (clean_text(x) for x in locs))) or None

            out.append(
                RawPosting(
                    external_id=str(j.get("id")),
                    title=clean_text(j.get("title")),
                    url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{token}",
                    apply_url=j.get("applyUrl"),
                    description=clean_text(j.get("descriptionPlain")) or None,
                    location_raw=loc_str,
                    department=clean_text(j.get("department") or j.get("team")) or None,
                    employment_type=clean_text(j.get("employmentType")) or None,
                    remote_hint="remote" if j.get("isRemote") else None,
                    posted_at=parse_datetime(j.get("publishedAt")),
                    updated_at=parse_datetime(j.get("updatedAt")),
                    salary_min=summary.get("min"),
                    salary_max=summary.get("max"),
                    salary_currency=summary.get("currencyCode"),
                    raw={k: v for k, v in j.items() if k not in ("descriptionHtml", "descriptionPlain")},
                )
            )
        return out
