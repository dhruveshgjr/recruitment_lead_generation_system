from __future__ import annotations

from ..normalize import clean_text, detect_remote, parse_datetime
from .base import HttpClient, JobSource, RawPosting
from .greenhouse import html_to_text


class LeverSource(JobSource):
    provider = "lever"
    BASE = "https://api.lever.co/v0/postings/{token}"

    async def fetch(self, token: str) -> list[RawPosting]:
        out: list[RawPosting] = []
        cursor: str | None = None
        skip = 0

        for _ in range(100):  # hard safety cap: 10,000 postings
            params: dict[str, object] = {"mode": "json", "limit": 100}
            if cursor:
                params["offset"] = cursor
            elif skip:
                params["skip"] = skip

            data = await self.client.get_json(self.BASE.format(token=token), **params)
            if isinstance(data, dict):
                page = data.get("data") or data.get("postings") or []
                cursor = data.get("next")
            elif isinstance(data, list):
                page = data
                cursor = None
            else:
                break

            if not isinstance(page, list) or not page:
                break

            for j in page:
                if not isinstance(j, dict):
                    continue
                cats = j.get("categories") or {}
                desc_parts = [
                    j.get("descriptionPlain")
                    or html_to_text(j.get("description"))
                    or ""
                ]
                for listing in j.get("lists") or []:
                    if isinstance(listing, dict):
                        desc_parts.append(
                            f"{listing.get('text', '')} "
                            f"{html_to_text(listing.get('content')) or ''}"
                        )
                desc = clean_text(" ".join(desc_parts)) or None

                out.append(
                    RawPosting(
                        external_id=str(j.get("id") or ""),
                        title=clean_text(j.get("text")),
                        url=j.get("hostedUrl") or f"https://jobs.lever.co/{token}",
                        apply_url=j.get("applyUrl"),
                        description=desc,
                        location_raw=clean_text(cats.get("location")) or None,
                        department=clean_text(
                            cats.get("team") or cats.get("department")
                        ) or None,
                        employment_type=clean_text(cats.get("commitment")) or None,
                        remote_hint=j.get("workplaceType")
                        or detect_remote(cats.get("location")),
                        posted_at=parse_datetime(j.get("createdAt")),
                        updated_at=parse_datetime(j.get("updatedAt")),
                        raw={
                            k: v
                            for k, v in j.items()
                            if k not in ("description", "lists")
                        },
                    )
                )

            if cursor:
                skip = 0
                continue
            if len(page) < 100:
                break
            skip += len(page)

        return out
