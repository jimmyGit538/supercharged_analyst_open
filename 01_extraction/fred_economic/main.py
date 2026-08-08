"""Extract FRED (Federal Reserve Economic Data) time series into BigQuery `raw`.

Runs as a Cloud Run Job: executes to completion and exits.

Series covered (118 total):
  - 16 national macro indicators (rates, labour, inflation, GDP, housing, sentiment)
  - 51 state-level FHFA house price indices   (ATNHPIUS<FIPS>000A, annual)
  - 51 state-level QCEW average weekly wages  (ENUC<FIPS>40010SA, quarterly)

A series id that FRED rejects is logged and skipped rather than failing the run —
see UnknownSeriesError. Check the job logs after the first run and correct any
rejected ids in the lists below.

Incremental strategy: per-series date watermark read from the destination table.
A series with no watermark is loaded in full; a series with a watermark is re-pulled
from that date forward so FRED's revisions to already-published observations are
picked up. Duplicates that this creates are resolved in the dbt staging layer, which
keeps one row per (series_id, date) by latest extracted_at.
"""

import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────────

API_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_API_KEY = os.getenv("FRED_API_KEY")

BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION") or os.getenv("BQ_PROJECT")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")
BQ_TABLE_NAME = "fred_economic_observations"

PAGE_LIMIT = 1000          # FRED maximum observations per request
REQUEST_SLEEP_SECONDS = 0.6  # ~100 req/min against a 120 req/min cap
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 30
LOAD_BATCH_ROWS = 50_000
MAX_BYTES_BILLED = 1 * 1024**3  # 1 GiB ceiling on the watermark query

MISSING_VALUE_SENTINEL = "."

# 16 national macro series.
NATIONAL_SERIES = [
    "FEDFUNDS",     # Federal Funds Rate (monthly)
    "DGS10",        # 10-Year Treasury Yield (daily)
    "DGS2",         # 2-Year Treasury Yield (daily)
    "MORTGAGE30US",  # 30-Year Fixed Mortgage Rate (weekly)
    "UNRATE",       # Unemployment Rate (monthly)
    "PAYEMS",       # Total Nonfarm Payrolls (monthly)
    "CPIAUCSL",     # CPI, All Urban Consumers (monthly)
    "CPILFESL",     # Core CPI, ex food and energy (monthly)
    "PCEPI",        # PCE Price Index (monthly)
    "GDP",          # Nominal GDP (quarterly)
    "GDPC1",        # Real GDP, chained 2017 dollars (quarterly)
    "HOUST",        # Housing Starts (monthly)
    "UMCSENT",      # UMich Consumer Sentiment (monthly)
    "INDPRO",       # Industrial Production Index (monthly)
    "MSPUS",        # Median Sales Price of Houses Sold (quarterly)
    "AHETPI",       # Average Hourly Earnings, private (monthly)
]

# 50 states + DC, as 2-digit FIPS codes.
STATE_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12",
    "13", "15", "16", "17", "18", "19", "20", "21", "22", "23",
    "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
    "34", "35", "36", "37", "38", "39", "40", "41", "42", "44",
    "45", "46", "47", "48", "49", "50", "51", "53", "54", "55",
    "56",
]

# FHFA all-transactions house price index, annual, one series per state.
# FRED pads the 2-digit state FIPS to a 5-character area code: 06 -> 06000.
STATE_HPI_SERIES = [f"ATNHPIUS{fips}000A" for fips in STATE_FIPS]

# QCEW average weekly wages, quarterly, one series per state.
STATE_WAGE_SERIES = [f"ENUC{fips}40010SA" for fips in STATE_FIPS]

ALL_SERIES = NATIONAL_SERIES + STATE_HPI_SERIES + STATE_WAGE_SERIES

BQ_SCHEMA = [
    bigquery.SchemaField("series_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("value", "FLOAT"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def table_id() -> str:
    return f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE_NAME}"


class UnknownSeriesError(RuntimeError):
    """FRED rejected the series id (HTTP 400).

    Raised per series rather than aborting the run, so one retired or mistyped
    id does not cost the other ~117 series their daily load. main() reports
    every rejected id and fails the job only if nothing at all was extracted.
    """


# ── Extraction ───────────────────────────────────────────────────────────────────


def _request_page(series_id: str, offset: int, observation_start: str | None) -> dict:
    """GET one page of observations, retrying on 429 and 5xx."""
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",  # FRED defaults to XML
        "limit": PAGE_LIMIT,
        "offset": offset,
        "sort_order": "asc",
    }
    if observation_start:
        params["observation_start"] = observation_start

    for attempt in range(MAX_ATTEMPTS):
        response = requests.get(
            f"{API_BASE_URL}/series/observations",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()
            wait = 2**attempt * 5
            print(
                f"[extract] {series_id}: HTTP {response.status_code}, "
                f"retrying in {wait}s (attempt {attempt + 1}/{MAX_ATTEMPTS})"
            )
            time.sleep(wait)
            continue

        # 400 means FRED does not recognise this series id or parameter.
        if response.status_code == 400:
            raise UnknownSeriesError(f"{series_id}: {response.text.strip()[:200]}")

        response.raise_for_status()
        return response.json()

    raise RuntimeError(f"[extract] {series_id}: exhausted {MAX_ATTEMPTS} attempts")


def extract_series(
    series_id: str,
    observation_start: str | None,
    extracted_at: str,
) -> list[dict]:
    """Return every observation for one series from observation_start onwards."""
    rows: list[dict] = []
    offset = 0

    while True:
        payload = _request_page(series_id, offset, observation_start)
        observations = payload.get("observations", [])

        for obs in observations:
            raw_value = obs.get("value")
            # "." is FRED's missing-data marker. It is not zero.
            value = (
                None
                if raw_value is None or raw_value == MISSING_VALUE_SENTINEL
                else float(raw_value)
            )
            rows.append(
                {
                    "series_id": series_id,
                    "date": obs["date"],
                    "value": value,
                    "extracted_at": extracted_at,
                }
            )

        # A short page is the last page. An empty first page means no data in
        # the requested range, which is expected and not an error.
        if len(observations) < PAGE_LIMIT:
            break

        offset += PAGE_LIMIT
        time.sleep(REQUEST_SLEEP_SECONDS)

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
    table.clustering_fields = ["series_id"]
    client.create_table(table)
    print(f"[bq] Created {table_id()}")


def load_watermarks(client: bigquery.Client) -> dict[str, str]:
    """Return {series_id: latest observation date} already in BigQuery.

    Empty on the first run, which triggers a full historical load per series.
    """
    query = f"""
        SELECT series_id, MAX(date) AS max_date
        FROM `{table_id()}`
        GROUP BY series_id
    """
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
    rows = client.query(query, job_config=job_config).result()
    watermarks = {row["series_id"]: row["max_date"].isoformat() for row in rows}
    print(f"[bq] Loaded watermarks for {len(watermarks)} series")
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
    if not FRED_API_KEY:
        raise OSError("FRED_API_KEY is not set")
    if not BQ_PROJECT:
        raise OSError("BQ_PROJECT_EXTRACTION (or BQ_PROJECT) is not set")


def main() -> None:
    validate_environment()

    client = bigquery.Client(project=BQ_PROJECT)
    ensure_table(client)
    watermarks = load_watermarks(client)

    extracted_at = datetime.now(timezone.utc).isoformat()
    pending: list[dict] = []
    total_rows = 0
    empty_series: list[str] = []
    rejected_series: list[str] = []

    for index, series_id in enumerate(ALL_SERIES, start=1):
        # Re-pull from the watermark date rather than the day after it, so FRED's
        # revisions to the most recent observation are captured.
        observation_start = watermarks.get(series_id)

        try:
            rows = extract_series(series_id, observation_start, extracted_at)
        except UnknownSeriesError as exc:
            rejected_series.append(series_id)
            print(f"[extract] ({index}/{len(ALL_SERIES)}) {series_id}: REJECTED — {exc}")
            time.sleep(REQUEST_SLEEP_SECONDS)
            continue

        if rows:
            pending.extend(rows)
            total_rows += len(rows)
        else:
            empty_series.append(series_id)

        print(
            f"[extract] ({index}/{len(ALL_SERIES)}) {series_id}: {len(rows)} rows"
            f"{'' if observation_start is None else f' since {observation_start}'}"
        )

        if len(pending) >= LOAD_BATCH_ROWS:
            append_rows(client, pending)
            pending = []

        time.sleep(REQUEST_SLEEP_SECONDS)

    append_rows(client, pending)

    if empty_series:
        print(
            f"[main] {len(empty_series)} series returned no new observations: "
            f"{', '.join(empty_series)}"
        )

    if rejected_series:
        print(
            f"[main] WARNING: FRED rejected {len(rejected_series)} series id(s). "
            f"Correct or remove them: {', '.join(rejected_series)}"
        )

    if rejected_series and total_rows == 0:
        # Every series failed — a bad key or a wholesale id problem, not a quiet day.
        raise RuntimeError(
            f"No observations extracted and {len(rejected_series)} series were "
            f"rejected by FRED. Check FRED_API_KEY and the series ids."
        )

    if total_rows == 0:
        # Expected on a same-day re-run; not an error.
        print("[main] No new observations across any series. Exiting.")
        return

    print(
        f"[main] Done. {total_rows} rows loaded from "
        f"{len(ALL_SERIES) - len(rejected_series)}/{len(ALL_SERIES)} series."
    )


if __name__ == "__main__":
    main()
