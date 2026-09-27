import datetime as dt

import httpx
import pytest

from hiringleads.sources.ashby import AshbySource
from hiringleads.sources.greenhouse import GreenhouseSource, html_to_text
from hiringleads.sources.lever import LeverSource


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get_json(self, url, **params):
        self.calls.append((url, params))
        if isinstance(self.payload, list):
            return self.payload
        if callable(self.payload):
            return self.payload(params)
        return self.payload


@pytest.mark.asyncio
async def test_greenhouse_adapter():
    client = FakeClient({"jobs": [{
        "id": 1,
        "title": "Backend Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "location": {"name": "Austin, TX"},
        "content": "<p>Python</p>",
        "first_published": "2026-01-01T10:00:00Z",
    }]})
    rows = await GreenhouseSource(client).fetch("acme")
    assert len(rows) == 1
    assert rows[0].external_id == "1"
    assert "Python" in (rows[0].description or "")


@pytest.mark.asyncio
async def test_lever_adapter():
    client = FakeClient([{
        "id": "abc",
        "text": "SRE",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "categories": {"location": "Remote", "team": "Engineering"},
        "descriptionPlain": "Kubernetes",
        "createdAt": "2026-01-01T10:00:00Z",
    }])
    rows = await LeverSource(client).fetch("acme")
    assert rows[0].title == "SRE"
    assert rows[0].remote_hint == "remote"


@pytest.mark.asyncio
async def test_ashby_adapter():
    client = FakeClient({"jobs": [{
        "id": "abc",
        "title": "ML Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
        "isListed": True,
        "isRemote": True,
        "location": "Remote",
        "publishedAt": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).isoformat(),
        "compensation": {"compensationTierSummary": {"min": 150000, "max": 200000, "currencyCode": "USD"}},
        "descriptionPlain": "PyTorch",
    }]})
    rows = await AshbySource(client).fetch("acme")
    assert rows[0].salary_min == 150000
    assert rows[0].remote_hint == "remote"


def test_html_to_text():
    assert html_to_text("<p>Hello</p><li>World</li>") == "Hello World"


@pytest.mark.asyncio
async def test_lever_pagination_supports_next_cursor():
    calls = []

    def payload(params):
        calls.append(params)
        if len(calls) == 1:
            return {
                "data": [
                    {
                        "id": "1",
                        "text": "Backend Engineer",
                        "hostedUrl": "https://jobs.lever.co/acme/1",
                        "categories": {"location": "Remote"},
                    }
                ],
                "next": "cursor-2",
            }
        return {
            "data": [
                {
                    "id": "2",
                    "text": "SRE",
                    "hostedUrl": "https://jobs.lever.co/acme/2",
                    "categories": {"location": "New York, NY"},
                }
            ],
            "next": None,
        }

    client = FakeClient(payload)
    rows = await LeverSource(client).fetch("acme")
    assert [row.external_id for row in rows] == ["1", "2"]
    assert calls[0]["limit"] == 100
    assert calls[1]["offset"] == "cursor-2"
