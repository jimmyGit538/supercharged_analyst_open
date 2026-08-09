---
name: api-open-meteo
description: >
  Open-Meteo API reference. Auto-invoke when writing code that calls the
  Open-Meteo API, building Open-Meteo extractors, or answering questions
  about Open-Meteo endpoints, parameters, or response shapes. Do NOT load
  for general weather discussions unrelated to the Open-Meteo API.
---

# Open-Meteo API

## Key facts
- Base URL (historical/archive): `https://archive-api.open-meteo.com/v1/archive`
- Base URL (forecast, not used by this project): `https://api.open-meteo.com/v1/forecast`
- Auth: **none** for non-commercial use — no signup, no key, no `.env` entry, no
  Secret Manager secret. Commercial use requires an `apikey` param against a
  `customer-` prefixed host; not applicable here.
- Rate limit: 600 requests/minute, 5,000/hour, 10,000/day (free, non-commercial)
- License: CC BY 4.0 — attribution required on redistribution
  (`https://open-meteo.com/`)
- Project usage: `01_extraction/open_meteo/main.py`, BQ table:
  `raw.open_meteo_daily_weather`. This is the repo's zero-setup reference
  pipeline — the one `setup-fork` provisions and verifies, because it needs
  no manual API-key signup before `terraform apply`. Contrast with
  `.claude/skills/api-fred/SKILL.md`, which documents a keyed source.

## Endpoint used

### GET /v1/archive
- **Purpose:** Returns daily/hourly historical weather for one or more
  locations across a date range, from ERA5/ERA5-Land reanalysis.
- **Key parameters:**
  - `latitude`, `longitude` — WGS84 coordinates (required)
  - `start_date`, `end_date` — `YYYY-MM-DD`, inclusive (required)
  - `daily` — comma-separated variable list, e.g.
    `temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max`
  - `timezone` — defaults to GMT; project uses `UTC` explicitly
- **No pagination:** one request returns the entire requested date range in a
  single JSON payload — unlike FRED, there is no offset/limit loop.
- **Response shape:**
  ```json
  {
    "latitude": 40.71, "longitude": -74.01,
    "timezone": "UTC", "utc_offset_seconds": 0,
    "daily_units": {"time": "iso8601", "temperature_2m_max": "°C", "..."},
    "daily": {
      "time": ["2024-01-01", "2024-01-02", "..."],
      "temperature_2m_max": [5.1, 4.8, "..."],
      "temperature_2m_min": [-1.2, -0.9, "..."],
      "precipitation_sum": [0.0, 2.3, "..."],
      "wind_speed_10m_max": [18.4, 22.1, "..."]
    }
  }
  ```
  Each `daily.<variable>` array is index-aligned with `daily.time` — row `i`
  across every array belongs to `daily.time[i]`.

## Response quirks
- Values are numeric (not strings, unlike FRED). A gap (e.g. sensor/model gap
  for that day) is returned as JSON `null`, not a sentinel string — no
  string-to-float coercion needed, just pass `None` through.
- The most recent ~5 days of archive data are provisional and get revised as
  the ERA5 model run finalizes. `01_extraction/open_meteo/main.py` caps
  `end_date` at `today - 6 days` (`ARCHIVE_LAG_DAYS`) to avoid requesting
  dates the archive hasn't settled yet.
- Requesting a date range with no data (e.g. before a location's coverage
  starts) returns empty arrays, not an HTTP error.

## Error handling
- HTTP 429: rate limit exceeded — retry with exponential backoff
  (`wait = 2 ** attempt * 5` seconds, max 5 attempts)
- HTTP 5xx: server error — same retry logic as 429
- HTTP 400: invalid parameters (e.g. bad lat/lon) — not expected in normal
  operation since this project's location list is fixed and pre-validated

## Rate limiting
- Cap: 600 requests/minute — with ~20 fixed locations, this project sleeps
  only 0.2s between requests as a courtesy, not because the cap is at risk

## Locations extracted (~20 total)
A fixed list of major world cities spanning every inhabited continent,
defined in `01_extraction/open_meteo/main.py::LOCATIONS` (id, name, country,
latitude, longitude). Add a location by appending to that list — no
coordination with any other file is required since there is no per-series
allowlist on the API side (unlike FRED's series ids).

## Incremental strategy
- Per-location date watermark: `MAX(date)` from
  `raw.open_meteo_daily_weather WHERE location_id = ?`
- No watermark → full historical load from `OPEN_METEO_START_DATE`
  (default `2015-01-01`, overridable via env var)
- Watermark exists → re-pull from the watermark date forward (not
  watermark + 1) to catch Open-Meteo's revisions to provisional recent days
- Write disposition: `WRITE_APPEND`
- Deduplication on `(location_id, date)` keeping latest `extracted_at` is
  handled in dbt staging
- `maximum_bytes_billed = 1 GB` on all watermark queries
