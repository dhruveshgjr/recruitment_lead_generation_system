"""Pure normalization functions used by every source adapter."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata

from dateutil import parser as dateparser

from .taxonomy import (
    COUNTRY_ALIASES,
    REMOTE_PATTERNS,
    US_STATES,
    US_STATE_CODES,
    _SENIORITY_RE,
)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s+#./-]")
_PAREN = re.compile(r"\([^)]*\)")
_BRACKET = re.compile(r"\[[^\]]*\]")
_COUNTRIES_BY_LEN = tuple(sorted(COUNTRY_ALIASES.items(), key=lambda kv: -len(kv[0])))
_STATES_BY_LEN = tuple(sorted(US_STATES.items(), key=lambda kv: -len(kv[0])))
_COUNTRY_RE = {
    alias: re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.IGNORECASE)
    for alias, _ in _COUNTRIES_BY_LEN
}
_STATE_RE = {
    alias: re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.IGNORECASE)
    for alias, _ in _STATES_BY_LEN
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    return _WS.sub(" ", value).strip()


def normalize_title(title: str) -> str:
    """Canonical title for matching/dedupe while preserving meaningful terms."""
    text = clean_text(title).lower()
    if not text:
        return ""

    text = _PAREN.sub(" ", text)
    text = _BRACKET.sub(" ", text)
    text = re.sub(
        r"\s*[-–—|,]\s*(?:remote|hybrid|onsite|on-site)\s*$",
        " ",
        text,
    )
    text = re.sub(
        r"\s*[-–—|]\s*[a-z .]+,\s*[a-z]{2}\s*$",
        " ",
        text,
    )
    text = re.sub(
        r"\s+\b(?:req|requisition|job|position)\s*#?\s*[\w-]{3,}\b",
        " ",
        text,
    )
    text = re.sub(r"\b(?:m/f/d|m/w/d|w/m/d|f/m/d)\b", " ", text)
    text = re.sub(r"\b\d{4,}\b", " ", text)
    text = re.sub(
        r"\b(?:remote|hybrid|onsite|on-site|full[- ]time|part[- ]time|contract)\b",
        " ",
        text,
    )
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def parse_seniority(title: str, description: str | None = None) -> str | None:
    for name, rx in _SENIORITY_RE:
        if rx.search(title or ""):
            return name
    if description:
        head = description[:1200]
        for name, rx in _SENIORITY_RE:
            if rx.search(head):
                return name
    return None


def detect_remote(text: str | None, hint: str | None = None) -> str:
    value = clean_text(hint).lower()
    if value in {"remote", "fully remote", "telecommute", "telecommuting"}:
        return "remote"
    if value in {"hybrid", "partially remote"}:
        return "hybrid"
    if value in {"onsite", "on-site", "on site", "office"}:
        return "onsite"

    text = clean_text(text)
    if not text:
        return "unknown"
    for rx, label in REMOTE_PATTERNS:
        if rx.search(text):
            return label
    return "unknown"


def parse_location(raw: str | None) -> dict[str, str | None]:
    """Best-effort location parser; it never pretends a free-text location is exact."""
    out: dict[str, str | None] = {
        "city": None,
        "region": None,
        "country": None,
        "remote_type": detect_remote(raw),
    }
    text = clean_text(raw)
    if not text:
        return out

    low = text.lower()

    for alias, code in _COUNTRIES_BY_LEN:
        if _COUNTRY_RE[alias].search(low):
            out["country"] = code
            break

    if out["country"] in (None, "US"):
        for name, code in _STATES_BY_LEN:
            if _STATE_RE[name].search(low):
                out["region"] = code
                out["country"] = "US"
                break
        else:
            match = re.search(r"\b([A-Z]{2})\b\s*$", text)
            if match and match.group(1) in US_STATE_CODES:
                out["region"] = match.group(1)
                out["country"] = "US"

    parts = [piece.strip() for piece in re.split(r"[,|/]| - ", text) if piece.strip()]
    for piece in parts:
        lower = piece.lower()
        if lower in COUNTRY_ALIASES or lower in US_STATES or lower in US_STATE_CODES:
            continue
        if any(rx.search(piece) for rx, _ in REMOTE_PATTERNS):
            continue
        if 1 < len(piece) < 60 and not piece.isdigit():
            out["city"] = piece
            break

    return out


def parse_datetime(value) -> dt.datetime | None:
    """Accept ISO-ish strings, epoch seconds/milliseconds, or datetime."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        if ts <= 0:
            return None
        try:
            return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if value.isdigit():
            return parse_datetime(int(value))
        try:
            parsed = dateparser.parse(value)
        except (ValueError, OverflowError, TypeError):
            return None
        if parsed is None:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def content_hash(*parts: str | None) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(clean_text(part).encode("utf-8", "ignore"))
        digest.update(b"\x00")
    return digest.hexdigest()


def dedupe_bucket(company_slug: str, country: str | None) -> str:
    """Indexed fuzzy-match bucket. This is intentionally NOT a hash."""
    return f"{company_slug[:80]}|{(country or '??')[:2]}".lower()


def dedupe_key(
    company_slug: str,
    normalized_title: str,
    country: str | None,
) -> str:
    """Stable content fingerprint retained for audit/debugging."""
    return hashlib.sha1(
        f"{company_slug}|{normalized_title[:120]}|{country or '??'}".encode("utf-8")
    ).hexdigest()


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    return clean_text(url).rstrip()


def slugify(name: str) -> str:
    value = clean_text(name).lower()
    value = re.sub(
        r"\b(?:inc|llc|ltd|limited|corp|corporation|gmbh|sa|srl|bv|nv|plc|co|company|group|holdings)\b\.?",
        "",
        value,
    )
    value = _PUNCT.sub("", value)
    value = re.sub(r"[\s-]+", "-", value).strip("-")
    return value or "unknown"


def truncate(value: str | None, n: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= n else value[: n - 1] + "…"
