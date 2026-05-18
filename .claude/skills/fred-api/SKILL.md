---
name: fred-api
description: >
  FRED (Federal Reserve Economic Data) API reference. Auto-invoke when writing
  code that calls the FRED API, building FRED extractors, or answering questions
  about FRED endpoints, parameters, or response shapes. Do NOT load for general
  discussions unrelated to the FRED API.
---

# FRED API

## Key facts
- Base URL: `https://api.stlouisfed.org/fred`
- Auth: query parameter `api_key=<FRED_API_KEY>`
- Rate limit: 120 requests/minute
- Project usage: `01_extraction/fred_economic/main.py`, BQ table: `raw.fred_economic_observations`,
  Secret: `fred-api-key` (Secret Manager), env var: `FRED_API_KEY`

## Endpoints used

### GET /series/observations
- **Purpose:** Returns time-series observations (date + value pairs) for a given series ID
- **Key parameters:**
  - `series_id` — FRED series identifier (e.g. `FEDFUNDS`, `DGS10`)
  - `api_key` — authentication
  - `file_type=json` — must be set explicitly; defaults to XML
  - `limit` — max observations per page (max 1000)
  - `offset` — zero-based row offset for pagination
  - `observation_start` — `YYYY-MM-DD` filter; omit for full history
  - `sort_order` — `asc` (oldest first) or `desc` (newest first)
- **Pagination:** offset-based. Increment `offset` by `limit` each page. End of data when `len(observations) < limit`.
- **Response shape:**
  ```json
  {
    "realtime_start": "2024-01-01",
    "realtime_end":   "2024-01-01",
    "observation_start": "1776-07-04",
    "observation_end":   "9999-12-31",
    "units":  "lin",
    "output_type": 1,
    "file_type": "json",
    "order_by": "observation_date",
    "sort_order": "asc",
    "count": 942,
    "offset": 0,
    "limit": 1000,
    "observations": [
      {"realtime_start": "...", "realtime_end": "...", "date": "2024-01-01", "value": "5.33"},
      ...
    ]
  }
  ```

## Response quirks
- `value` is always a STRING. Cast to `float` after checking for `"."` (missing data marker) — treat `"."` as NULL.
- Observations are returned in `asc` order by default when `sort_order=asc` is specified.
- The `count` field in the response body is the total number of matching observations (not just the current page) — useful for logging but not needed for pagination logic.
- `realtime_start` / `realtime_end` reflect data vintage, not the observation date — ignore these in the BQ schema; only `date` and `value` are needed.

## Error handling
- HTTP 429: rate limit exceeded — retry with exponential backoff (`wait = 2 ** attempt * 5` seconds, max 5 attempts)
- HTTP 5xx: server error — same retry logic as 429
- HTTP 400: bad series ID or parameter — raises immediately (not retried)
- The API does not return an HTTP error for series with no data in the requested range; it returns an empty `observations` array — check `len(observations) == 0` and exit cleanly

## Rate limiting
- Cap: 120 requests/minute
- Project approach: `time.sleep(0.6)` between series requests (~100 req/min headroom)
- With ~120 series total, one full run takes ~72 seconds minimum just from sleep

## Series extracted (120 total)
- 16 national macro series (interest rates, labor, inflation, GDP, housing, consumer)
- 51 state-level FHFA House Price Indices: `ATNHPIUS<FIPS>A` pattern
- 51 state-level Average Weekly Wages (QCEW): `ENUC<FIPS>40010SA` pattern

## Incremental strategy
- Per-series date watermark: `MAX(date)` from `raw.fred_economic_observations WHERE series_id = ?`
- No watermark → full historical load (no `observation_start` param)
- Watermark exists → set `observation_start = watermark_date` (re-pulls from last date to catch FRED data revisions)
- Write disposition: `WRITE_APPEND`
- Deduplication on `(series_id, date)` keeping latest `extracted_at` is handled in dbt staging
- `maximum_bytes_billed = 1 GB` on all watermark queries
