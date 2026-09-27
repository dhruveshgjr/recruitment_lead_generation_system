"""Source adapter contract plus a shared polite HTTP client."""
from __future__ import annotations

import abc
import asyncio
import datetime as dt
import email.utils
import json
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
import structlog

from ..config import settings

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class RawPosting:
    external_id: str
    title: str
    url: str
    description: str | None = None
    location_raw: str | None = None
    department: str | None = None
    employment_type: str | None = None
    remote_hint: str | None = None
    posted_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    apply_url: str | None = None
    company_name: str | None = None
    company_website: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(slots=True)
class ResponseMeta:
    status_code: int
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    url: str | None = None


class TokenBucket:
    """Per-host token bucket with a small burst for normal API request patterns."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / max(self.rate, 0.001))


class HttpClient:
    """Shared async client with host-level politeness and bounded retries.

    The client retries transport failures, 408, 429 and 5xx. It never blindly
    retries arbitrary 4xx responses.
    """

    def __init__(self) -> None:
        s = settings()
        timeout = httpx.Timeout(
            timeout=s.http_timeout,
            connect=s.http_connect_timeout,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": s.http_user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            },
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=s.http_concurrency * 2,
                max_keepalive_connections=s.http_concurrency,
            ),
            http2=True,
        )
        self._buckets: dict[str, TokenBucket] = {}
        self._buckets_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(s.http_concurrency)
        self._max_bytes = s.http_max_response_mb * 1024 * 1024

    async def _bucket(self, host: str) -> TokenBucket:
        async with self._buckets_lock:
            if host not in self._buckets:
                s = settings()
                self._buckets[host] = TokenBucket(s.per_host_rate, s.per_host_burst)
            return self._buckets[host]

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=dt.timezone.utc)
                return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return 0.0

    @staticmethod
    def _backoff(attempt: int, cap: float = 30.0) -> float:
        return min(cap, (2**attempt) + random.random())

    async def get_json(self, url: str, **params) -> dict | list:
        return await self._request("GET", url, params=params or None)

    async def get_text(self, url: str, **params) -> str:
        result = await self._request("GET", url, params=params or None)
        if isinstance(result, dict):
            return str(result.get("_text") or "")
        return ""

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **params,
    ) -> tuple[dict | list, ResponseMeta]:
        result, meta = await self._request(
            "GET", url, params=params or None, headers=headers, with_meta=True
        )
        return result, meta

    async def _request(self, method: str, url: str, *, with_meta: bool = False, **kw):
        s = settings()
        host = httpx.URL(url).host or "unknown"
        bucket = await self._bucket(host)
        last_exc: Exception | None = None

        for attempt in range(s.http_retries + 1):
            await bucket.acquire()
            try:
                async with self._sem:
                    async with self._client.stream(method, url, **kw) as response:
                        status = response.status_code

                        if status in {408, 429} or 500 <= status < 600:
                            last_exc = httpx.HTTPStatusError(
                                f"retryable response {status}",
                                request=response.request,
                                response=response,
                            )
                            if attempt >= s.http_retries:
                                break
                            retry_after = self._retry_after(response.headers.get("Retry-After"))
                            await asyncio.sleep(max(retry_after, self._backoff(attempt)))
                            continue

                        response.raise_for_status()

                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > self._max_bytes:
                                raise httpx.HTTPError(
                                    f"response exceeds configured {s.http_max_response_mb} MB limit",
                                    request=response.request,
                                )

                        body = bytes(content)
                        ct = response.headers.get("content-type", "").lower()
                        try:
                            if "json" in ct:
                                payload = json.loads(body)
                            else:
                                charset = response.encoding or "utf-8"
                                payload = {"_text": body.decode(charset, errors="replace")}
                        except (ValueError, UnicodeDecodeError, LookupError) as exc:
                            raise httpx.HTTPError(
                                f"invalid response payload from {response.url}: {exc}",
                                request=response.request,
                            ) from exc

                        if with_meta:
                            return payload, ResponseMeta(
                                status_code=status,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                                content_type=ct,
                                url=str(response.url),
                            )
                        return payload

            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt >= s.http_retries:
                    break
                await asyncio.sleep(self._backoff(attempt))

        raise last_exc or RuntimeError(f"request failed: {method} {url}")

    async def aclose(self) -> None:
        await self._client.aclose()


class RobotsPolicy:
    """24-hour robots.txt cache shared by HTML/JSON-LD extraction."""

    def __init__(self, ttl_hours: int = 24) -> None:
        self.ttl = dt.timedelta(hours=ttl_hours)
        self._cache: dict[str, tuple[dt.datetime, object | None]] = {}
        self._lock = asyncio.Lock()

    async def allowed(self, client: HttpClient, url: str) -> bool:
        from urllib.robotparser import RobotFileParser

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        now = dt.datetime.now(dt.timezone.utc)

        async with self._lock:
            cached = self._cache.get(origin)
            if cached and now - cached[0] < self.ttl:
                rp = cached[1]
                return True if rp is None else rp.can_fetch(settings().http_user_agent, url)

        rp: RobotFileParser | None = None
        try:
            text = await client.get_text(f"{origin}/robots.txt")
            if text.strip():
                parser = RobotFileParser()
                parser.set_url(f"{origin}/robots.txt")
                parser.parse(text.splitlines())
                rp = parser
        except Exception as exc:
            # A robots endpoint failing does not prove disallow. Record the
            # exception and fail open, matching the baseline's conservative behavior.
            log.warning("robots.fetch_failed", origin=origin, error=str(exc))

        async with self._lock:
            self._cache[origin] = (now, rp)
        return True if rp is None else rp.can_fetch(settings().http_user_agent, url)


class JobSource(abc.ABC):
    provider: str = "base"
    supports_discovery: bool = False

    def __init__(self, client: HttpClient):
        self.client = client

    @abc.abstractmethod
    async def fetch(self, token: str) -> list[RawPosting]:
        """Fetch all currently-listed postings for a board token."""

    async def discover(self) -> list[tuple[str, str]]:
        """Return [(company_name, token), ...] if supports_discovery."""
        return []
