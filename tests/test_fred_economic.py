"""Unit tests for 01_extraction/fred_economic/main.py.

These are the reference tests for a keyed, offset-paginated extractor. Copy
this file for a new source of the same shape and keep the same checks:
sentinel handling, pagination, per-entity failure isolation, watermark
pass-through, and the all-rejected failure.
"""

import pytest
from conftest import FakeResponse, load_extractor

fred = load_extractor("fred_economic")


def page(observations: list[dict]) -> dict:
    return {"observations": observations}


# ── extract_series: values and pagination ───────────────────────────────────────


def test_missing_value_sentinel_becomes_none_not_zero(monkeypatch):
    monkeypatch.setattr(
        fred,
        "_request_page",
        lambda series_id, offset, start: page(
            [
                {"date": "2024-01-01", "value": "3.5"},
                {"date": "2024-01-02", "value": "."},
                {"date": "2024-01-03", "value": None},
            ]
        ),
    )

    rows = fred.extract_series("UNRATE", None, "ts")

    assert [r["value"] for r in rows] == [3.5, None, None]
    assert all(r["series_id"] == "UNRATE" and r["extracted_at"] == "ts" for r in rows)


def test_pagination_advances_offset_and_stops_on_short_page(monkeypatch, no_sleep):
    no_sleep(fred)
    full_page = [{"date": f"2024-01-{i:02d}", "value": "1"} for i in range(fred.PAGE_LIMIT)]
    short_page = [{"date": "2030-01-01", "value": "2"}]
    offsets: list[int] = []

    def fake_page(series_id, offset, start):
        offsets.append(offset)
        return page(full_page if offset == 0 else short_page)

    monkeypatch.setattr(fred, "_request_page", fake_page)

    rows = fred.extract_series("DGS10", None, "ts")

    assert offsets == [0, fred.PAGE_LIMIT]
    assert len(rows) == fred.PAGE_LIMIT + 1


def test_empty_first_page_is_not_an_error(monkeypatch):
    monkeypatch.setattr(fred, "_request_page", lambda *a: page([]))

    assert fred.extract_series("GDP", "2024-01-01", "ts") == []


# ── _request_page: error signals ─────────────────────────────────────────────────


def test_http_400_raises_unknown_series_error(monkeypatch):
    monkeypatch.setattr(fred.requests, "get", lambda *a, **kw: FakeResponse(400, text="Bad Request"))

    with pytest.raises(fred.UnknownSeriesError):
        fred._request_page("NOPE", 0, None)


def test_request_page_retries_on_5xx(monkeypatch, no_sleep):
    sleeps = no_sleep(fred)
    responses = iter([FakeResponse(502), FakeResponse(200, page([]))])
    monkeypatch.setattr(fred.requests, "get", lambda *a, **kw: next(responses))

    assert fred._request_page("UNRATE", 0, None) == page([])
    assert sleeps == [5]


# ── main: watermarks and failure isolation ──────────────────────────────────────


def test_main_passes_watermark_and_skips_rejected_series(monkeypatch, fake_bigquery):
    state = fake_bigquery(fred, watermarks={"UNRATE": "2024-05-01"})
    monkeypatch.setattr(fred.time, "sleep", lambda s: None)
    monkeypatch.setattr(fred, "ALL_SERIES", ["UNRATE", "RETIRED", "GDP"])

    starts: dict[str, str | None] = {}

    def fake_extract(series_id, observation_start, extracted_at):
        starts[series_id] = observation_start
        if series_id == "RETIRED":
            raise fred.UnknownSeriesError("RETIRED: not found")
        return [{"series_id": series_id, "date": "2024-06-01", "value": 1.0}]

    monkeypatch.setattr(fred, "extract_series", fake_extract)

    fred.main()  # one rejected series must not fail the run

    assert starts == {"UNRATE": "2024-05-01", "RETIRED": None, "GDP": None}
    assert sorted(r["series_id"] for r in state["appended"]) == ["GDP", "UNRATE"]


def test_main_fails_when_every_series_is_rejected(monkeypatch, fake_bigquery):
    fake_bigquery(fred)
    monkeypatch.setattr(fred.time, "sleep", lambda s: None)
    monkeypatch.setattr(fred, "ALL_SERIES", ["A", "B"])

    def always_reject(series_id, observation_start, extracted_at):
        raise fred.UnknownSeriesError(f"{series_id}: bad key")

    monkeypatch.setattr(fred, "extract_series", always_reject)

    with pytest.raises(RuntimeError, match="Check FRED_API_KEY"):
        fred.main()
