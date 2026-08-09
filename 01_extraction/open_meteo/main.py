"""Extract Open-Meteo historical daily weather into BigQuery `raw`.

Runs as a Cloud Run Job: executes to completion and exits.

Open-Meteo's archive API (ERA5/ERA5-Land reanalysis) requires no API key for
non-commercial use, so this source needs zero secrets and zero manual signup —
it is the pipeline a fresh fork provisions and verifies by default. See
`.claude/skills/setup-fork/SKILL.md`.

Data: CC BY 4.0, https://open-meteo.com/ — attribution required on redistribution.

Locations: ~20 major world cities (fixed list below), analogous to FRED's
state list. One HTTP request per location returns the entire requested date
range in a single JSON payload — no offset pagination needed.

Incremental strategy: per-location date watermark read from the destination
table. A location with no watermark is loaded from OPEN_METEO_START_DATE; a
location with a watermark is re-pulled from that date forward, because
Open-Meteo's most recent ~5 days of archive data are provisional and get
revised as the ERA5 run finalizes. Duplicates that this creates are resolved
in the dbt staging layer, which keeps one row per (location_id, date) by
latest extracted_at.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────────

API_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION") or os.getenv("BQ_PROJECT")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")
BQ_TABLE_NAME = "open_meteo_daily_weather"

# Archive data lags a few days behind real time as ERA5 runs finalize.
ARCHIVE_LAG_DAYS = 6
DEFAULT_START_DATE = os.getenv("OPEN_METEO_START_DATE", "2015-01-01")

DAILY_VARIABLES = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"

REQUEST_SLEEP_SECONDS = 0.2  # 20 locations well under the 600 req/min free-tier cap
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 30
MAX_BYTES_BILLED = 1 * 1024**3  # 1 GiB ceiling on the watermark query

# ~20 major world cities spanning every inhabited continent.
LOCATIONS = [
    {"location_id": "new_york", "name": "New York", "country": "US", "latitude": 40.7128, "longitude": -74.0060},
    {"location_id": "los_angeles", "name": "Los Angeles", "country": "US", "latitude": 34.0522, "longitude": -118.2437},
    {"location_id": "mexico_city", "name": "Mexico City", "country": "MX", "latitude": 19.4326, "longitude": -99.1332},
    {"location_id": "sao_paulo", "name": "Sao Paulo", "country": "BR", "latitude": -23.5505, "longitude": -46.6333},
    {"location_id": "buenos_aires", "name": "Buenos Aires", "country": "AR", "latitude": -34.6037, "longitude": -58.3816},
    {"location_id": "london", "name": "London", "country": "GB", "latitude": 51.5074, "longitude": -0.1278},
    {"location_id": "paris", "name": "Paris", "country": "FR", "latitude": 48.8566, "longitude": 2.3522},
    {"location_id": "berlin", "name": "Berlin", "country": "DE", "latitude": 52.5200, "longitude": 13.4050},
    {"location_id": "madrid", "name": "Madrid", "country": "ES", "latitude": 40.4168, "longitude": -3.7038},
    {"location_id": "moscow", "name": "Moscow", "country": "RU", "latitude": 55.7558, "longitude": 37.6173},
    {"location_id": "cairo", "name": "Cairo", "country": "EG", "latitude": 30.0444, "longitude": 31.2357},
    {"location_id": "lagos", "name": "Lagos", "country": "NG", "latitude": 6.5244, "longitude": 3.3792},
    {"location_id": "johannesburg", "name": "Johannesburg", "country": "ZA", "latitude": -26.2041, "longitude": 28.0473},
    {"location_id": "nairobi", "name": "Nairobi", "country": "KE", "latitude": -1.2921, "longitude": 36.8219},
    {"location_id": "dubai", "name": "Dubai", "country": "AE", "latitude": 25.2048, "longitude": 55.2708},
    {"location_id": "mumbai", "name": "Mumbai", "country": "IN", "latitude": 19.0760, "longitude": 72.8777},
    {"location_id": "beijing", "name": "Beijing", "country": "CN", "latitude": 39.9042, "longitude": 116.4074},
    {"location_id": "tokyo", "name": "Tokyo", "country": "JP", "latitude": 35.6762, "longitude": 139.6503},
    {"location_id": "singapore", "name": "Singapore", "country": "SG", "latitude": 1.3521, "longitude": 103.8198},
    {"location_id": "sydney", "name": "Sydney", "country": "AU", "latitude": -33.8688, "longitude": 151.2093},
]

BQ_SCHEMA = [
    bigquery.SchemaField("location_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("location_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("country", "STRING"),
    bigquery.SchemaField("latitude", "FLOAT"),
    bigquery.SchemaField("longitude", "FLOAT"),
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("temperature_max_c", "FLOAT"),
    bigquery.SchemaField("temperature_min_c", "FLOAT"),
    bigquery.SchemaField("precipitation_sum_mm", "FLOAT"),
    bigquery.SchemaField("wind_speed_max_kmh", "FLOAT"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def table_id() -> str:
    return f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE_NAME}"


def archive_end_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=ARCHIVE_LAG_DAYS)).strftime("%Y-%m-%d")


# ── Extraction ───────────────────────────────────────────────────────────────────


def _request(location: dict, start_date: str, end_date: str) -> dict:
    """GET the full date range for one location, retrying on 429 and 5xx."""
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "start_date": start_date,
        "end_date": end_date,
        "daily": DAILY_VARIABLES,
        "timezone": "UTC",
    }

    for attempt in range(MAX_ATTEMPTS):
        response = requests.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()
            wait = 2**attempt * 5
            print(
                f"[extract] {location['location_id']}: HTTP {response.status_code}, "
                f"retrying in {wait}s (attempt {attempt + 1}/{MAX_ATTEMPTS})"
            )
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response.json()

    raise RuntimeError(f"[extract] {location['location_id']}: exhausted {MAX_ATTEMPTS} attempts")


def extract_location(location: dict, start_date: str, end_date: str, extracted_at: str) -> list[dict]:
    """Return every daily observation for one location across [start_date, end_date]."""
    if start_date > end_date:
        return []

    payload = _request(location, start_date, end_date)
    daily = payload.get("daily", {})
    dates = daily.get("time", [])

    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    wind_max = daily.get("wind_speed_10m_max", [])

    rows = []
    for i, date in enumerate(dates):
        rows.append(
            {
                "location_id": location["location_id"],
                "location_name": location["name"],
                "country": location["country"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "date": date,
                "temperature_max_c": temp_max[i] if i < len(temp_max) else None,
                "temperature_min_c": temp_min[i] if i < len(temp_min) else None,
                "precipitation_sum_mm": precip[i] if i < len(precip) else None,
                "wind_speed_max_kmh": wind_max[i] if i < len(wind_max) else None,
                "extracted_at": extracted_at,
            }
        )
    return rows


# ── BigQuery ─────────────────────────────────────────────────────────────────────


def ensure_table(client: bigquery.Client) -> None:
    """Create the destination table on first run."""
    try:
        client.get_table(table_id())
        return
    except NotFound:
        pass

    table = bigquery.Table(table_id(), schema=BQ_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.MONTH,
        field="date",
    )
    table.clustering_fields = ["location_id"]
    client.create_table(table)
    print(f"[bq] Created {table_id()}")


def load_watermarks(client: bigquery.Client) -> dict[str, str]:
    """Return {location_id: latest observation date} already in BigQuery.

    Empty on the first run, which triggers a full historical load per location.
    """
    query = f"""
        SELECT location_id, MAX(date) AS max_date
        FROM `{table_id()}`
        GROUP BY location_id
    """
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
    rows = client.query(query, job_config=job_config).result()
    watermarks = {row["location_id"]: row["max_date"].isoformat() for row in rows}
    print(f"[bq] Loaded watermarks for {len(watermarks)} location(s)")
    return watermarks


def append_rows(client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        return
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    client.load_table_from_json(rows, table_id(), job_config=job_config).result()
    print(f"[bq] Appended {len(rows)} rows into {table_id()}")


# ── Entrypoint ───────────────────────────────────────────────────────────────────


def validate_environment() -> None:
    if not BQ_PROJECT:
        raise OSError("BQ_PROJECT_EXTRACTION (or BQ_PROJECT) is not set")


def main() -> None:
    validate_environment()

    client = bigquery.Client(project=BQ_PROJECT)
    ensure_table(client)
    watermarks = load_watermarks(client)

    end_date = archive_end_date()
    extracted_at = datetime.now(timezone.utc).isoformat()
    pending: list[dict] = []
    total_rows = 0
    empty_locations: list[str] = []

    for index, location in enumerate(LOCATIONS, start=1):
        # Re-pull from the watermark date rather than the day after it, so
        # Open-Meteo's revisions to the most recent provisional days are captured.
        start_date = watermarks.get(location["location_id"], DEFAULT_START_DATE)

        rows = extract_location(location, start_date, end_date, extracted_at)

        if rows:
            pending.extend(rows)
            total_rows += len(rows)
        else:
            empty_locations.append(location["location_id"])

        print(
            f"[extract] ({index}/{len(LOCATIONS)}) {location['location_id']}: "
            f"{len(rows)} rows since {start_date}"
        )

        time.sleep(REQUEST_SLEEP_SECONDS)

    append_rows(client, pending)

    if empty_locations:
        print(
            f"[main] {len(empty_locations)} location(s) returned no new observations: "
            f"{', '.join(empty_locations)}"
        )

    if total_rows == 0:
        # Expected on a same-day re-run; not an error.
        print("[main] No new observations across any location. Exiting.")
        return

    print(f"[main] Done. {total_rows} rows loaded from {len(LOCATIONS)} location(s).")


if __name__ == "__main__":
    main()
