"""Small Prometheus registry with stable metric names."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

BOARDS_SCANNED = Counter(
    "hiringleads_boards_scanned_total",
    "Board scan attempts",
    ["provider", "status"],
    registry=REGISTRY,
)
POSTINGS_CREATED = Counter(
    "hiringleads_postings_created_total",
    "Canonical postings created",
    registry=REGISTRY,
)
POSTINGS_UPDATED = Counter(
    "hiringleads_postings_updated_total",
    "Existing postings whose content changed",
    registry=REGISTRY,
)
POSTINGS_DEDUPED = Counter(
    "hiringleads_postings_deduped_total",
    "Near-duplicate postings folded into an existing posting",
    registry=REGISTRY,
)
POSTINGS_DEACTIVATED = Counter(
    "hiringleads_postings_deactivated_total",
    "Postings deactivated after consecutive misses",
    registry=REGISTRY,
)
BULK_SYNCS = Counter(
    "hiringleads_bulk_sync_events_total",
    "Detected bulk import/synchronization events",
    registry=REGISTRY,
)
INGEST_DURATION = Histogram(
    "hiringleads_ingest_duration_seconds",
    "Per-board ingestion duration",
    ["provider"],
    registry=REGISTRY,
)
DELIVERIES = Counter(
    "hiringleads_deliveries_total",
    "Digest delivery attempts",
    ["status"],
    registry=REGISTRY,
)
ACTIVE_BOARDS = Gauge(
    "hiringleads_active_boards",
    "Active board count as last sampled",
    registry=REGISTRY,
)

MATCH_SCAN_CAP_HITS = Counter(
    "hiringleads_match_scan_cap_hits_total",
    "Watchlists whose candidate scan reached the configured cap",
    registry=REGISTRY,
)
