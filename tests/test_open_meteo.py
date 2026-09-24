"""Unit tests for 01_extraction/open_meteo/main.py.

These are the reference tests for a keyless, one-request-per-entity extractor.
Copy this file for a new source of the same shape and keep the same five
checks: row alignment, empty range, retry, watermark start dates, empty run.
"""

import pytest
from conftest import FakeResponse, load_extractor

om = load_extractor("open_meteo")

LOCATION = {
    "location_id": "test_city",
    "name": "Test City",
    "country": "XX",
    "latitude": 1.0,
    "longitude": 2.0,
}


# ── extract_location ─────────────────────────────────────────────────────────────


def test_extract_location_aligns_values_by_date_and_nulls_short_arrays(monkeypatch):
    payload = {
        "daily": {
            "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "temperature_2m_max": [10.0, 11.0, 12.0],
            "temperature_2m_min": [1.0, 2.0],  # one short: last day must be None
            "precipitation_sum": [0.0, 0.5, 0.0],
            "wind_speed_10m_max": [20.0, 21.0, 22.0],
        }
    }
    monkeypatch.setattr(om, "_request", lambda location, start, end: payload)

    rows = om.extract_location(LOCATION, "2024-01-01", "2024-01-03", "2024-01-10T00:00:00+00:00")

    assert [r["date"] for r in rows] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert [r["temperature_max_c"] for r in rows] == [10.0, 11.0, 12.0]
    assert [r["temperature_min_c"] for r in rows] == [1.0, 2.0, None]
    assert all(r["location_id"] == "test_city" for r in rows)
    assert all(r["extracted_at"] == "2024-01-10T00:00:00+00:00" for r in rows)


def test_extract_location_returns_nothing_when_start_is_after_end(monkeypatch):
    def fail(*args):
        raise AssertionError("no request should be made for an empty range")

    monkeypatch.setattr(om, "_request", fail)

    assert om.extract_location(LOCATION, "2024-01-05", "2024-01-01", "ts") == []


# ── _request ─────────────────────────────────────────────────────────────────────


def test_request_retries_on_429_then_returns_payload(monkeypatch, no_sleep):
    sleeps = no_sleep(om)
    responses = iter([FakeResponse(429), FakeResponse(503), FakeResponse(200, {"daily": {}})])
    monkeypatch.setattr(om.requests, "get", lambda *a, **kw: next(responses))

    assert om._request(LOCATION, "2024-01-01", "2024-01-02") == {"daily": {}}
    assert sleeps == [5, 10]  # exponential backoff: 2**0*5, 2**1*5


def test_request_gives_up_after_max_attempts(monkeypatch, no_sleep):
    no_sleep(om)
    monkeypatch.setattr(om.requests, "get", lambda *a, **kw: FakeResponse(500))

    with pytest.raises(RuntimeError):
        om._request(LOCATION, "2024-01-01", "2024-01-02")


# ── main: watermark handling ──────────────────────────────────────────────────────


def test_main_starts_each_location_from_its_watermark_or_default(monkeypatch, fake_bigquery):
    state = fake_bigquery(om, watermarks={"new_york": "2024-06-01"})
    monkeypatch.setattr(om.time, "sleep", lambda s: None)
    monkeypatch.setattr(om, "LOCATIONS", [om.LOCATIONS[0], om.LOCATIONS[1]])  # new_york, los_angeles
    monkeypatch.setattr(om, "archive_end_date", lambda: "2024-06-10")

    starts: dict[str, str] = {}

    def fake_extract(location, start_date, end_date, extracted_at):
        starts[location["location_id"]] = start_date
        return [{"location_id": location["location_id"], "date": start_date}]

    monkeypatch.setattr(om, "extract_location", fake_extract)

    om.main()

    # A watermark is re-pulled inclusive, so revisions to that day are captured.
    assert starts["new_york"] == "2024-06-01"
    # No watermark means a full backfill from the configured start date.
    assert starts["los_angeles"] == om.DEFAULT_START_DATE
    assert len(state["appended"]) == 2


def test_main_exits_cleanly_when_nothing_is_new(monkeypatch, fake_bigquery):
    state = fake_bigquery(om)
    monkeypatch.setattr(om.time, "sleep", lambda s: None)
    monkeypatch.setattr(om, "extract_location", lambda *a: [])

    om.main()  # must not raise

    assert state["appended"] == []
