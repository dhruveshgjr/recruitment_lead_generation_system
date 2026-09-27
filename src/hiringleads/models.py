"""PostgreSQL data model.

The model deliberately separates:
- companies from ATS boards,
- observations from canonical postings,
- delivery watermark from delivery attempts,
- prediction from human review.

That separation is what makes the system replayable and auditable.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_name_search", "name"),
        Index("ix_companies_country_industry", "hq_country", "industry"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    hq_city: Mapped[str | None] = mapped_column(String(120))
    hq_region: Mapped[str | None] = mapped_column(String(120))
    hq_country: Mapped[str | None] = mapped_column(String(2), index=True)
    headcount_band: Mapped[str | None] = mapped_column(String(20))  # external enrichment only
    open_roles_band: Mapped[str | None] = mapped_column(String(20), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    boards: Mapped[list["JobBoard"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", lazy="selectin"
    )


class JobBoard(Base):
    __tablename__ = "job_boards"
    __table_args__ = (
        UniqueConstraint("provider", "token", name="uq_board_provider_token"),
        Index("ix_boards_active_provider", "is_active", "provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    token: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    last_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)
    empty_streak: Mapped[int] = mapped_column(Integer, default=0)
    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified: Mapped[str | None] = mapped_column(String(500))
    discovered_via: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    company: Mapped[Company] = relationship(back_populates="boards", lazy="joined")


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("board_id", "external_id", name="uq_posting_board_external"),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_posting_salary_order",
        ),
        Index("ix_postings_family_first_seen", "role_family", "first_seen_at"),
        Index("ix_postings_company_active", "company_id", "is_active"),
        Index("ix_postings_bucket_recent", "dedupe_bucket", "last_seen_at"),
        Index("ix_postings_active_first_seen", "is_active", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("job_boards.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )

    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(400))
    normalized_title: Mapped[str] = mapped_column(String(400), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(60))

    seniority: Mapped[str | None] = mapped_column(String(20), index=True)
    role_family: Mapped[str | None] = mapped_column(String(40), index=True)
    role_family_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classification_evidence: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    location_raw: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    remote_type: Mapped[str | None] = mapped_column(String(12), index=True)

    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(3))

    url: Mapped[str] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))

    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_source: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    missed_scans: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_bulk_import: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_bucket: Mapped[str] = mapped_column(String(100), index=True)
    repost_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("job_postings.id", ondelete="SET NULL")
    )

    # Sanitized adapter output only. Never assume provider JSON is safe to keep.
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class Recruiter(Base):
    __tablename__ = "recruiters"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    agency: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    plan: Mapped[str] = mapped_column(String(40), default="trial")
    monthly_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    watchlists: Mapped[list["Watchlist"]] = relationship(
        back_populates="recruiter", cascade="all, delete-orphan"
    )


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        Index("ix_watchlists_delivery", "is_active", "email_enabled", "last_delivered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(
        ForeignKey("recruiters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))

    role_families: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    exclude_skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    seniorities: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=True)

    min_score: Mapped[float] = mapped_column(Float, default=45.0)
    max_age_days: Mapped[int] = mapped_column(Integer, default=14)
    daily_cap: Mapped[int] = mapped_column(Integer, default=40)
    include_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    exclude_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recruiter: Mapped[Recruiter] = relationship(back_populates="watchlists", lazy="joined")


class DeliveredLead(Base):
    """Watermark: a job is never intentionally sent twice to one watchlist."""

    __tablename__ = "delivered_leads"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "job_id", name="uq_delivered_wl_job"),
        Index("ix_delivered_watchlist_time", "watchlist_id", "delivered_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    delivered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    """One durable row per board scan; useful for operations and replay."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_board_started", "board_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("job_boards.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    deduped: Mapped[int] = mapped_column(Integer, default=0)
    deactivated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class DeliveryRun(Base):
    """Per-watchlist delivery attempt with an auditable outcome."""

    __tablename__ = "delivery_runs"
    __table_args__ = (
        Index("ix_delivery_runs_watchlist_started", "watchlist_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), index=True)
    lead_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(300), index=True)


class ClassificationReview(Base):
    """Human feedback queue for low-confidence classifications."""

    __tablename__ = "classification_reviews"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_classification_review_job"),
        Index("ix_classification_review_pending", "reviewed_at", "confidence"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    predicted_family: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    corrected_family: Mapped[str | None] = mapped_column(String(40))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
