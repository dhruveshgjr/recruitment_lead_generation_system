from __future__ import annotations

from .ashby import AshbySource
from .base import JobSource
from .greenhouse import GreenhouseSource
from .hn_whoishiring import HackerNewsSource
from .jsonld import JsonLdSource
from .lever import LeverSource
from .recruitee import RecruiteeSource
from .smartrecruiters import SmartRecruitersSource
from .workable import WorkableSource

REGISTRY: dict[str, type[JobSource]] = {
    GreenhouseSource.provider: GreenhouseSource,
    LeverSource.provider: LeverSource,
    AshbySource.provider: AshbySource,
    WorkableSource.provider: WorkableSource,
    SmartRecruitersSource.provider: SmartRecruitersSource,
    RecruiteeSource.provider: RecruiteeSource,
    JsonLdSource.provider: JsonLdSource,
    HackerNewsSource.provider: HackerNewsSource,
}

#: Providers whose board token is a URL rather than an identifier.
URL_TOKEN_PROVIDERS = {"jsonld"}


def get_source_class(provider: str) -> type[JobSource]:
    try:
        return REGISTRY[provider]
    except KeyError as e:
        raise KeyError(f"unknown provider '{provider}'. known: {sorted(REGISTRY)}") from e
