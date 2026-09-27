from __future__ import annotations

import asyncio
import datetime as dt
import email.message
import hashlib
from dataclasses import dataclass
from email.utils import formataddr
from pathlib import Path

import aiosmtplib
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings
from ..matching import Lead
from ..security import make_unsubscribe_token
from .csv_export import default_filename, leads_to_csv_bytes

log = structlog.get_logger(__name__)
_TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None


def render_html(
    watchlist_name: str,
    leads: list[Lead],
    *,
    window_hours: int = 24,
    now: dt.datetime | None = None,
    unsubscribe_url: str = "",
) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    template = _env.get_template("digest.html.j2")
    return template.render(
        watchlist={"name": watchlist_name},
        leads=leads,
        generated_at=now.strftime("%a %d %b %Y, %H:%M UTC"),
        window_hours=window_hours,
        unsubscribe_url=unsubscribe_url,
    )


def render_subject(watchlist_name: str, leads: list[Lead]) -> str:
    count = len(leads)
    if not leads:
        return f"{watchlist_name}: no new signals"
    company = leads[0].company[:80]
    return f"{count} new hiring signal{'s' if count != 1 else ''} — {company} + more"


def _plain_text_body(
    watchlist_name: str,
    leads: list[Lead],
    unsubscribe_url: str,
) -> str:
    lines = [
        f"{len(leads)} hiring signals — {watchlist_name}",
        "",
        "Public company hiring signals matched to your watchlist.",
        "",
    ]
    for lead in leads[:50]:
        location = lead.city or lead.country or (
            "Remote" if lead.remote_type == "remote" else "—"
        )
        lines.append(
            f"[{lead.score:.0f}] {lead.company} — {lead.title} — {location} — {lead.url}"
        )
    if len(leads) > 50:
        lines.append(f"...and {len(leads) - 50} more in the attached CSV.")
    lines.extend(
        [
            "",
            "Source: public company career/job pages.",
            "No personal contact data is included in these leads.",
            f"Unsubscribe: {unsubscribe_url}",
        ]
    )
    return "\n".join(lines)


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in {421, 450, 451, 452}
    return isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            asyncio.TimeoutError,
            OSError,
        ),
    ) or "timeout" in str(exc).lower()


async def send_digest(
    *,
    to_email: str,
    watchlist_name: str,
    watchlist_id: int,
    leads: list[Lead],
    attach_csv: bool = True,
    window_hours: int = 24,
    now: dt.datetime | None = None,
    message_id: str | None = None,
) -> DeliveryResult:
    s = settings()
    if not s.smtp_host:
        return DeliveryResult(ok=False, error="smtp_not_configured")

    now = now or dt.datetime.now(dt.timezone.utc)
    unsubscribe_url = (
        f"{s.public_base_url.rstrip('/')}/unsubscribe/"
        f"{make_unsubscribe_token(watchlist_id)}"
    )
    html = render_html(
        watchlist_name,
        leads,
        window_hours=window_hours,
        now=now,
        unsubscribe_url=unsubscribe_url,
    )
    text = _plain_text_body(watchlist_name, leads, unsubscribe_url)
    if message_id is None:
        domain = s.smtp_from.rsplit("@", 1)[-1].strip() or "localhost"
        fingerprint = hashlib.sha256(
            (f"{watchlist_id}:" + ",".join(str(lead.job_id) for lead in leads)).encode("utf-8")
        ).hexdigest()[:24]
        message_id = f"<hl.{watchlist_id}.{fingerprint}@{domain}>"
    msg = email.message.EmailMessage()
    msg["From"] = formataddr(("Hiring Leads", s.smtp_from))
    msg["To"] = to_email
    msg["Subject"] = render_subject(watchlist_name, leads)
    msg["Message-ID"] = message_id
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["Precedence"] = "bulk"
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if attach_csv and leads:
        msg.add_attachment(
            leads_to_csv_bytes(leads),
            maintype="text",
            subtype="csv",
            filename=default_filename(watchlist_name, now),
        )

    last_error: Exception | None = None
    for attempt in range(s.delivery_retries + 1):
        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user,
                password=s.smtp_password,
                start_tls=s.smtp_starttls,
                timeout=s.smtp_timeout,
            )
            log.info("email.sent", watchlist_id=watchlist_id, leads=len(leads))
            return DeliveryResult(ok=True, message_id=message_id)
        except Exception as exc:
            last_error = exc
            if attempt >= s.delivery_retries or not _is_retryable(exc):
                break
            await asyncio.sleep(min(60.0, (2**attempt) + 0.5))

    error = f"{type(last_error).__name__}: {last_error}"[:2000]
    log.warning("email.send_failed", watchlist_id=watchlist_id, error=error)
    return DeliveryResult(ok=False, message_id=message_id, error=error)
