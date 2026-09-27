import datetime as dt

from hiringleads.normalize import (
    content_hash,
    dedupe_bucket,
    normalize_title,
    parse_datetime,
    parse_location,
    parse_seniority,
)


def test_normalize_title_removes_non_identity_suffixes():
    assert normalize_title("Senior Backend Engineer — Remote") == "senior backend engineer"


def test_parse_location_extracts_us_state_and_city():
    parsed = parse_location("Austin, Texas, United States")
    assert parsed["city"] == "Austin"
    assert parsed["region"] == "TX"
    assert parsed["country"] == "US"


def test_remote_detection_is_explicit():
    assert parse_location("London, UK — fully remote")["remote_type"] == "remote"


def test_parse_datetime_handles_epoch_milliseconds():
    value = parse_datetime(1726000000000)
    assert value.tzinfo == dt.timezone.utc
    assert value.year == 2024


def test_hash_and_bucket_are_stable():
    assert content_hash("A", "B") == content_hash("A", "B")
    assert dedupe_bucket("Acme", "US") == "acme|us"
