"""Validated application settings.

All environment variables use the ``HL_`` prefix. Production secrets must be
provided explicitly; insecure development defaults are rejected when
``HL_ENV=production``.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HL_",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "development"

    # storage
    database_url: str = "postgresql+asyncpg://hiringleads:hiringleads@localhost:5432/hiringleads"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout: float = Field(default=30.0, gt=0, le=300)

    # http / crawl politeness
    http_timeout: float = Field(default=30.0, gt=0, le=300)
    http_connect_timeout: float = Field(default=10.0, gt=0, le=120)
    http_concurrency: int = Field(default=24, ge=1, le=256)
    http_retries: int = Field(default=3, ge=0, le=8)
    http_max_response_mb: int = Field(default=12, ge=1, le=100)
    http_user_agent: str = (
        "HiringLeadsBot/1.0 (+https://example.com/bot-info; replace-this-address)"
    )
    per_host_rate: float = Field(default=2.0, gt=0, le=20)
    per_host_burst: int = Field(default=4, ge=1, le=32)
    robots_cache_ttl_hours: int = Field(default=24, ge=1, le=168)

    # pipeline
    dedupe_window_days: int = Field(default=45, ge=1, le=365)
    dedupe_threshold: int = Field(default=92, ge=80, le=100)
    repost_threshold: int = Field(default=95, ge=90, le=100)
    inactive_after_misses: int = Field(default=3, ge=1, le=20)
    repost_window_days: int = Field(default=75, ge=1, le=365)
    bulk_post_threshold: int = Field(default=15, ge=5, le=500)
    bulk_growth_factor: float = Field(default=3.0, gt=1.0, le=20)
    max_description_chars: int = Field(default=50000, ge=1000, le=500000)
    raw_max_bytes: int = Field(default=20000, ge=1000, le=200000)
    low_confidence_threshold: float = Field(default=0.50, ge=0, le=1)
    match_scan_cap: int = Field(default=25000, ge=1000, le=250000)

    # delivery
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "leads@example.com"
    smtp_starttls: bool = True
    smtp_timeout: float = Field(default=45.0, gt=0, le=180)
    delivery_throttle_seconds: float = Field(default=1.5, ge=0, le=60)
    delivery_retries: int = Field(default=3, ge=0, le=6)

    # api / public links
    api_key: str = "dev-key-change-me"
    public_base_url: str = "http://localhost:8000"
    unsubscribe_secret: str = "dev-unsubscribe-secret-change-me"

    # worker
    ingest_every_hours: int = Field(default=6, ge=1, le=24)
    delivery_hour_utc: int = Field(default=13, ge=0, le=23)
    discovery_day_utc: int = Field(default=6, ge=0, le=6)
    discovery_hour_utc: int = Field(default=3, ge=0, le=23)
    discovery_max_boards: int = Field(default=2000, ge=1, le=10000)

    # observability
    log_level: str = "INFO"
    metrics_enabled: bool = True
    auto_create_schema: bool = False

    @field_validator("log_level")
    @classmethod
    def normalize_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.env.lower() == "production":
            if self.api_key == "dev-key-change-me":
                raise ValueError("HL_API_KEY must be changed in production")
            if self.unsubscribe_secret == "dev-unsubscribe-secret-change-me":
                raise ValueError("HL_UNSUBSCRIBE_SECRET must be changed in production")
            if "example.com" in self.http_user_agent.lower():
                raise ValueError("HL_HTTP_USER_AGENT must contain a real bot contact")
            if self.smtp_from.endswith("@example.com"):
                raise ValueError("HL_SMTP_FROM must contain a real sender address")
            if not self.public_base_url.lower().startswith("https://"):
                raise ValueError("HL_PUBLIC_BASE_URL must use https in production")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
