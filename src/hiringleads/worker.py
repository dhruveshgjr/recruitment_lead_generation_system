"""Scheduler process. Runs ingestion every 6h, delivery every morning."""
from __future__ import annotations

import asyncio
import signal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .delivery.runner import deliver_all
from .db import create_all, session_factory
from .discovery.probe import discover_via_commoncrawl
from .pipeline import run_all, summarize, upsert_board
from .sources.base import HttpClient

log = structlog.get_logger(__name__)


async def ingest_job() -> None:
    client = HttpClient()
    try:
        results = await run_all(session_factory(), client, concurrency=8)
        log.info("ingest.complete", **summarize(results))
    finally:
        await client.aclose()


async def discover_job() -> None:
    """Weekly Common Crawl sweep to grow the board registry."""
    client = HttpClient()
    try:
        boards = await discover_via_commoncrawl(client, pages_per_target=2)
        async with session_factory()() as s:
            added = 0
            for b in boards[:settings().discovery_max_boards]:
                await upsert_board(
                    s,
                    provider=b.provider,
                    token=b.token,
                    url=b.url,
                    discovered_via="commoncrawl",
                )
                added += 1
            await s.commit()
        log.info("discover.complete", candidates=len(boards), upserted=added)
    finally:
        await client.aclose()


async def deliver_job() -> None:
    await deliver_all()


async def main() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    if settings().auto_create_schema:
        await create_all()
    else:
        log.info("worker.schema", mode="migrations_required")

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        ingest_job,
        CronTrigger(hour=f"*/{settings().ingest_every_hours}"),
        id="ingest",
        max_instances=1,
    )
    scheduler.add_job(
        deliver_job,
        CronTrigger(hour=settings().delivery_hour_utc, minute=0),
        id="deliver",
        max_instances=1,
    )
    scheduler.add_job(
        discover_job,
        CronTrigger(
            day_of_week=settings().discovery_day_utc,
            hour=settings().discovery_hour_utc,
        ),
        id="discover",
        max_instances=1,
    )
    scheduler.start()

    log.info("worker.started")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    scheduler.shutdown(wait=True)
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
