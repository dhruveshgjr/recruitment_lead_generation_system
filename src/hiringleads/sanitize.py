"""Provider payload sanitization.

Raw provider JSON is useful for debugging, but storing arbitrary upstream
payloads forever is a needless privacy and retention liability. This function
keeps bounded, non-obvious-PII fields and strips keys commonly used for people,
comments, reviewer notes and contact information.
"""
from __future__ import annotations

import re
from typing import Any

from .config import settings

_SENSITIVE_KEY = re.compile(
    r"(email|e-?mail|phone|mobile|full.?name|first.?name|last.?name|"
    r"applicant|candidate|resume|cv|reviewer|comment|note|message|"
    r"contact|linkedin|twitter|github|address|street)",
    re.IGNORECASE,
)
_MAX_DEPTH = 5
_MAX_ITEMS = 100


def sanitize_raw(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return None

    max_bytes = settings().raw_max_bytes

    if isinstance(value, str):
        text = value.strip()
        encoded = text.encode("utf-8", "ignore")
        if len(encoded) <= max_bytes:
            return text
        return encoded[: max_bytes - 3].decode("utf-8", "ignore") + "..."

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                break
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                continue
            cleaned = sanitize_raw(child, depth=depth + 1)
            if cleaned is not None and cleaned != {} and cleaned != []:
                output[key_text[:120]] = cleaned
        return output

    if isinstance(value, (list, tuple)):
        return [
            cleaned
            for child in list(value)[:_MAX_ITEMS]
            if (cleaned := sanitize_raw(child, depth=depth + 1)) is not None
        ]

    return str(value)[:500]


def sanitize_description(description: str | None) -> str | None:
    if not description:
        return None
    value = description.strip()
    return value[: settings().max_description_chars]
