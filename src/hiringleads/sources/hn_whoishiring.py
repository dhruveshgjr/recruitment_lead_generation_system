"""Hacker News "Who is hiring?" — the highest signal-to-noise source for
engineering roles at small/mid companies, who are disproportionately likely
to be first-time users of agency recruiters.

Format is a comment convention, not a schema:
    Company | Role | Location | Remote | Salary | Link
"""
from __future__ import annotations

import datetime as dt
import re

from ..normalize import clean_text, parse_datetime
from .base import HttpClient, JobSource, RawPosting

ALGOLIA = "https://hn.algolia.com/api/v1"
_STORY = re.compile(r"Ask HN:\s*Who is hiring\?", re.IGNORECASE)
_PIPE = re.compile(r"\s*[|•·]\s*|\s+[–—]\s+")


class HackerNewsSource(JobSource):
    provider = "hn_whoishiring"

    async def _latest_thread_id(self) -> str | None:
        data = await self.client.get_json(
            f"{ALGOLIA}/search",
            query="Ask HN: Who is hiring?",
            tags="story",
            hitsPerPage=5,
        )
        for hit in (data.get("hits") or []):
            title = hit.get("title") or ""
            if _STORY.search(title):
                return str(hit.get("objectID"))
        return None

    async def fetch(self, token: str = "latest") -> list[RawPosting]:
        story_id = await self._latest_thread_id()
        if not story_id:
            return []

        out: list[RawPosting] = []
        page = 0
        while page < 20:
            data = await self.client.get_json(
                f"{ALGOLIA}/search",
                tags=f"comment,story_{story_id}",
                hitsPerPage=200,
                page=page,
            )
            hits = data.get("hits") or []
            if not hits:
                break

            for h in hits:
                text = h.get("comment_text") or ""
                if not text:
                    continue
                parsed = self._parse_comment(h.get("objectID"), text, h.get("created_at"))
                if parsed:
                    out.extend(parsed)

            page += 1
            if page >= (data.get("nbPages") or 1):
                break

        return out

    def _parse_comment(self, cid, html_text, created_at) -> list[RawPosting]:
        import html as html_mod

        raw = re.sub(r"<p>", "\n", html_text)
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = html_mod.unescape(raw)
        lines = [clean_text(l) for l in raw.split("\n") if clean_text(l)]
        if not lines:
            return []

        header = lines[0]
        parts = [p for p in _PIPE.split(header) if p]
        if len(parts) < 2:
            return []

        company = parts[0][:200]
        body = clean_text(" ".join(lines[1:]))
        posted = parse_datetime(created_at)

        postings: list[RawPosting] = []
        # One comment often lists several roles.
        for i, role in enumerate(parts[1:6]):
            role_l = role.lower()
            if any(k in role_l for k in ("remote", "onsite", "on-site", "hybrid", "usa", "europe", "worldwide")):
                continue
            postings.append(
                RawPosting(
                    external_id=f"{cid}-{i}",
                    title=clean_text(role),
                    url=f"https://news.ycombinator.com/item?id={cid}",
                    description=body or None,
                    location_raw=self._guess_location(parts),
                    company_name=company,
                    posted_at=posted,
                    updated_at=posted,
                    raw={"hn_id": cid, "header": header[:500]},
                )
            )
        return postings

    @staticmethod
    def _guess_location(parts: list[str]) -> str | None:
        for p in parts:
            pl = p.lower()
            if any(k in pl for k in ("remote", "onsite", "on-site", "hybrid", "usa", "eu", "europe", "worldwide", "anywhere")):
                return p[:200]
        return None
