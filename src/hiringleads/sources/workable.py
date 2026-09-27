from __future__ import annotations

from ..normalize import clean_text, detect_remote, parse_datetime
from .base import HttpClient, JobSource, RawPosting


class WorkableSource(JobSource):
    """Workable public account endpoint; tolerates common public payload shapes."""

    provider = "workable"
    BASE = "https://www.workable.com/api/accounts/{token}"

    async def fetch(self, token: str) -> list[RawPosting]:
        data = await self.client.get_json(self.BASE.format(token=token), details="true")
        if not isinstance(data, dict):
            return []

        company_name = clean_text(data.get("name") or data.get("account_name")) or None
        jobs = data.get("jobs") or data.get("offers") or data.get("results") or []
        if not isinstance(jobs, list):
            return []

        out: list[RawPosting] = []
        for j in jobs:
            if not isinstance(j, dict):
                continue
            location = j.get("location") or j.get("locations") or {}
            if isinstance(location, dict):
                location_raw = clean_text(
                    location.get("location_str") or location.get("name") or location.get("city")
                ) or None
                remote = bool(
                    location.get("telecommuting")
                    or location.get("remote")
                    or j.get("telecommuting")
                )
            elif isinstance(location, list):
                location_raw = clean_text(", ".join(str(x) for x in location if x)) or None
                remote = bool(j.get("telecommuting"))
            else:
                location_raw = clean_text(str(location)) or None
                remote = bool(j.get("telecommuting"))

            job = RawPosting(
                external_id=str(j.get("shortcode") or j.get("id") or ""),
                title=clean_text(j.get("title") or j.get("name")),
                url=j.get("url") or j.get("shortlink") or "",
                apply_url=j.get("application_url") or j.get("apply_url"),
                description=clean_text(
                    j.get("description") or j.get("description_text")
                ) or None,
                location_raw=location_raw,
                department=clean_text(
                    j.get("department") or j.get("department_name")
                ) or None,
                remote_hint="remote" if remote else detect_remote(location_raw),
                posted_at=parse_datetime(j.get("created_at") or j.get("published_at")),
                updated_at=parse_datetime(j.get("updated_at")),
                company_name=company_name,
                raw=j,
            )
            if job.external_id and job.title and job.url:
                out.append(job)
        return out
