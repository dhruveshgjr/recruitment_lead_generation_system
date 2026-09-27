"""Small stateless tokens used for public unsubscribe links."""
from __future__ import annotations

import base64
import hashlib
import hmac

from .config import settings


def make_unsubscribe_token(watchlist_id: int) -> str:
    payload = str(watchlist_id).encode()
    signature = hmac.new(
        settings().unsubscribe_secret.encode(),
        payload,
        hashlib.sha256,
    ).digest()
    enc = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return f"{enc(payload)}.{enc(signature)}"


def parse_unsubscribe_token(token: str) -> int | None:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        pad = lambda value: value + "=" * (-len(value) % 4)
        payload = base64.urlsafe_b64decode(pad(payload_b64))
        signature = base64.urlsafe_b64decode(pad(signature_b64))
    except (ValueError, TypeError):
        return None

    expected = hmac.new(
        settings().unsubscribe_secret.encode(),
        payload,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        return int(payload.decode())
    except (ValueError, UnicodeDecodeError):
        return None
