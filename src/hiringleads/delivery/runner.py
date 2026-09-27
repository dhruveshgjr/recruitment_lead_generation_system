"""Per-watchlist daily delivery with independent transactions."""
from __future__ import annotations

import asyncio
import hashlib

import structlog
from sqlalchemy import func, select

from ..config import settings
from ..db import session_factory
from ..matching import build_leads, mark_delivered
from ..models import DeliveryRun, Recruiter, Watchlist, utcnow
from ..observability import DELIVERIES
from .email import send_digest

log = structlog.get_logger(__name__)


async def deliver_all(*, dry_run: bool = False) -> dict[str, int]:
    factory = session_factory()
    s = settings()
    stats = {
        "watchlists": 0,
        "emailed": 0,
        "leads": 0,
        "skipped": 0,
        "failed": 0,
    }

    async with factory() as bootstrap:
        rows = list(
            (
                await bootstrap.execute(
                    select(Watchlist, Recruiter)
                    .join(Recruiter, Recruiter.id == Watchlist.recruiter_id)
                    .where(
                        Watchlist.is_active.is_(True),
                        Watchlist.email_enabled.is_(True),
                        Recruiter.is_active.is_(True),
                    )
                )
            ).all()
        )

    for index, (wl, recruiter) in enumerate(rows):
        stats["watchlists"] += 1
        if index:
            await asyncio.sleep(s.delivery_throttle_seconds)

        async with factory() as db:
            # Advisory namespace 2 is separate from board-ingestion namespace 1.
            # Holding this transaction lock through the send prevents two worker
            # processes from both emailing the same watchlist concurrently.
            await db.execute(select(func.pg_advisory_xact_lock(2, wl.id)))
            leads = await build_leads(db, wl, exclude_delivered=True)
            if not leads:
                stats["skipped"] += 1
                continue

            stats["leads"] += len(leads)
            if dry_run:
                log.info(
                    "deliver.dry_run",
                    watchlist_id=wl.id,
                    recruiter_id=recruiter.id,
                    leads=len(leads),
                )
                continue

            delivery = DeliveryRun(
                watchlist_id=wl.id,
                status="sending",
                lead_count=len(leads),
            )
            db.add(delivery)
            await db.flush()

            fingerprint = hashlib.sha256(
                (f"{wl.id}:" + ",".join(str(lead.job_id) for lead in leads)).encode("utf-8")
            ).hexdigest()[:24]
            smtp_domain = s.smtp_from.rsplit("@", 1)[-1].strip() or "localhost"
            stable_message_id = f"<hl.{wl.id}.{fingerprint}@{smtp_domain}>"
            delivery.message_id = stable_message_id
            result = await send_digest(
                to_email=recruiter.email,
                watchlist_name=wl.name,
                watchlist_id=wl.id,
                leads=leads,
                window_hours=24,
                message_id=stable_message_id,
            )
            delivery.finished_at = utcnow()
            delivery.message_id = result.message_id

            if result.ok:
                delivery.status = "sent"
                # Watermark only after the ESP accepted the message. This gives
                # at-least-once semantics and makes retries safe at the DB layer.
                await mark_delivered(db, wl.id, leads)
                stats["emailed"] += 1
                DELIVERIES.labels("sent").inc()
            else:
                delivery.status = "failed"
                delivery.error = result.error
                stats["failed"] += 1
                DELIVERIES.labels("failed").inc()

            await db.commit()

    log.info("deliver.done", **stats)
    return stats
