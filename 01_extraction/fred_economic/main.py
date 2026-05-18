"""
01_extraction/fred_economic/main.py

Extracts FRED (Federal Reserve Economic Data) observations for a fixed set of
series IDs and loads them into BigQuery raw.fred_economic_observations.

Incremental strategy: per-series date watermark stored in BigQuery.
  - Query MAX(date) for the series from the target table.
  - If no rows exist → full historical load (no observation_start param).
  - If watermark exists → re-pull from watermark date to catch FRED revisions.
  - Use WRITE_APPEND; deduplication handled downstream in dbt staging.

Rate limiting: 120 req/min cap. Sleep 0.6s between series requests (~100/min).
On HTTP 429 or 5xx: exponential backoff, max 5 attempts.
"""

import os
import time
import datetime
import logging
from dotenv import load_dotenv
import requests
from google.cloud import bigquery

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────────────────────

FRED_API_KEY = os.getenv("FRED_API_KEY")
BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")

_missing = [k for k, v in {
    "FRED_API_KEY": FRED_API_KEY,
    "BQ_PROJECT_EXTRACTION": BQ_PROJECT,
}.items() if not v]
if _missing:
    raise EnvironmentError(f"Required environment variables not set: {', '.join(_missing)}")

BQ_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.fred_economic_observations"
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# ── Series list ───────────────────────────────────────────────────────────────

SERIES_IDS = [
    # Interest rates & yield curve
    "FEDFUNDS",
    "DGS10",
    "DGS2",
    "MORTGAGE30US",
    # Labor market
    "UNRATE",
    "PAYEMS",
    # Inflation
    "CPIAUCSL",
    "CPILFESL",
    "PCEPI",
    # Growth
    "GDP",
    "GDPC1",
    # Housing & consumer
    "HOUST",
    "UMCSENT",
    "INDPRO",
    "MSPUS",
    "AHETPI",
    # State-level FHFA House Price Indices (all 50 states + DC)
    "ATNHPIUS01000A",  # AL
    "ATNHPIUS02000A",  # AK
    "ATNHPIUS04000A",  # AZ
    "ATNHPIUS05000A",  # AR
    "ATNHPIUS06000A",  # CA
    "ATNHPIUS08000A",  # CO
    "ATNHPIUS09000A",  # CT
    "ATNHPIUS10000A",  # DE
    "ATNHPIUS11000A",  # DC
    "ATNHPIUS12000A",  # FL
    "ATNHPIUS13000A",  # GA
    "ATNHPIUS15000A",  # HI
    "ATNHPIUS16000A",  # ID
    "ATNHPIUS17000A",  # IL
    "ATNHPIUS18000A",  # IN
    "ATNHPIUS19000A",  # IA
    "ATNHPIUS20000A",  # KS
    "ATNHPIUS21000A",  # KY
    "ATNHPIUS22000A",  # LA
    "ATNHPIUS23000A",  # ME
    "ATNHPIUS24000A",  # MD
    "ATNHPIUS25000A",  # MA
    "ATNHPIUS26000A",  # MI
    "ATNHPIUS27000A",  # MN
    "ATNHPIUS28000A",  # MS
    "ATNHPIUS29000A",  # MO
    "ATNHPIUS30000A",  # MT
    "ATNHPIUS31000A",  # NE
    "ATNHPIUS32000A",  # NV
    "ATNHPIUS33000A",  # NH
    "ATNHPIUS34000A",  # NJ
    "ATNHPIUS35000A",  # NM
    "ATNHPIUS36000A",  # NY
    "ATNHPIUS37000A",  # NC
    "ATNHPIUS38000A",  # ND
    "ATNHPIUS39000A",  # OH
    "ATNHPIUS40000A",  # OK
    "ATNHPIUS41000A",  # OR
    "ATNHPIUS42000A",  # PA
    "ATNHPIUS44000A",  # RI
    "ATNHPIUS45000A",  # SC
    "ATNHPIUS46000A",  # SD
    "ATNHPIUS47000A",  # TN
    "ATNHPIUS48000A",  # TX
    "ATNHPIUS49000A",  # UT
    "ATNHPIUS50000A",  # VT
    "ATNHPIUS51000A",  # VA
    "ATNHPIUS53000A",  # WA
    "ATNHPIUS54000A",  # WV
    "ATNHPIUS55000A",  # WI
    "ATNHPIUS56000A",  # WY
    # State-level Average Weekly Wages (QCEW)
    "ENUC010040010SA",  # AL
    "ENUC020040010SA",  # AK
    "ENUC040040010SA",  # AZ
    "ENUC050040010SA",  # AR
    "ENUC060040010SA",  # CA
    "ENUC080040010SA",  # CO
    "ENUC090040010SA",  # CT
    "ENUC100040010SA",  # DE
    "ENUC110040010SA",  # DC
    "ENUC120040010SA",  # FL
    "ENUC130040010SA",  # GA
    "ENUC150040010SA",  # HI
    "ENUC160040010SA",  # ID
    "ENUC170040010SA",  # IL
    "ENUC180040010SA",  # IN
    "ENUC190040010SA",  # IA
    "ENUC200040010SA",  # KS
    "ENUC210040010SA",  # KY
    "ENUC220040010SA",  # LA
    "ENUC230040010SA",  # ME
    "ENUC240040010SA",  # MD
    "ENUC250040010SA",  # MA
    "ENUC260040010SA",  # MI
    "ENUC270040010SA",  # MN
    "ENUC280040010SA",  # MS
    "ENUC290040010SA",  # MO
    "ENUC300040010SA",  # MT
    "ENUC310040010SA",  # NE
    "ENUC320040010SA",  # NV
    "ENUC330040010SA",  # NH
    "ENUC340040010SA",  # NJ
    "ENUC350040010SA",  # NM
    "ENUC360040010SA",  # NY
    "ENUC370040010SA",  # NC
    "ENUC380040010SA",  # ND
    "ENUC390040010SA",  # OH
    "ENUC400040010SA",  # OK
    "ENUC410040010SA",  # OR
    "ENUC420040010SA",  # PA
    "ENUC440040010SA",  # RI
    "ENUC450040010SA",  # SC
    "ENUC460040010SA",  # SD
    "ENUC470040010SA",  # TN
    "ENUC480040010SA",  # TX
    "ENUC490040010SA",  # UT
    "ENUC500040010SA",  # VT
    "ENUC510040010SA",  # VA
    "ENUC530040010SA",  # WA
    "ENUC540040010SA",  # WV
    "ENUC550040010SA",  # WI
    "ENUC560040010SA",  # WY
]

# ── BigQuery schema ───────────────────────────────────────────────────────────

BQ_SCHEMA = [
    bigquery.SchemaField("series_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("value", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

MAX_BYTES_BILLED = 1 * 1024 ** 3  # 1 GB safety cap on watermark queries


def get_watermark(bq_client: bigquery.Client, series_id: str) -> str | None:
    """
    Return the MAX(date) already loaded for this series_id, or None if the
    table does not yet have any rows for it.
    """
    query = f"""
        SELECT MAX(date) AS max_date
        FROM `{BQ_TABLE}`
        WHERE series_id = @series_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("series_id", "STRING", series_id)
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    try:
        results = list(bq_client.query(query, job_config=job_config).result())
        max_date = results[0].max_date if results else None
        return str(max_date) if max_date else None
    except Exception as exc:
        # Table may not exist yet on the very first run
        if "Not found" in str(exc) or "notFound" in str(exc):
            return None
        raise


def fetch_observations(series_id: str, observation_start: str | None) -> list[dict]:
    """
    Fetch all observations for a series from FRED with offset-based pagination.
    Returns a list of raw observation dicts from the API.
    Retries on HTTP 429 / 5xx with exponential backoff (max 5 attempts).
    """
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "limit": 1000,
        "sort_order": "asc",
    }
    if observation_start:
        params["observation_start"] = observation_start

    all_observations: list[dict] = []
    offset = 0

    while True:
        params["offset"] = offset
        response = _request_with_retry(
            f"{FRED_BASE_URL}/series/observations", params=params
        )
        data = response.json()
        batch = data.get("observations", [])
        all_observations.extend(batch)

        if len(batch) < 1000:
            break  # last page
        offset += len(batch)

    return all_observations


def _request_with_retry(url: str, params: dict) -> requests.Response:
    """GET with exponential backoff on 429 / 5xx. Max 5 attempts."""
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = (2 ** attempt) * 5
                log.warning(
                    "HTTP %s from FRED. Attempt %d/%d. Sleeping %ds.",
                    resp.status_code, attempt + 1, max_attempts, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            if attempt == max_attempts - 1:
                raise
            wait = (2 ** attempt) * 5
            log.warning("Request error: %s. Sleeping %ds.", exc, wait)
            time.sleep(wait)

    raise RuntimeError(f"FRED request failed after {max_attempts} attempts: {url}")


def transform_observations(
    series_id: str,
    raw_observations: list[dict],
    extracted_at: str,
) -> list[dict]:
    """
    Convert raw FRED observation dicts to BigQuery row dicts.
    Value "." (missing) is mapped to None (NULL in BQ).
    """
    rows = []
    for obs in raw_observations:
        raw_value = obs.get("value")
        value = None if raw_value == "." else float(raw_value)
        rows.append({
            "series_id": series_id,
            "date": obs["date"],          # already "YYYY-MM-DD" string
            "value": value,
            "extracted_at": extracted_at,
        })
    return rows


def append_to_bigquery(bq_client: bigquery.Client, rows: list[dict]) -> None:
    """Append rows to the target table using WRITE_APPEND."""
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition="WRITE_APPEND",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()
    log.info("[bq] Appended %d rows into %s", len(rows), BQ_TABLE)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    bq_client = bigquery.Client(project=BQ_PROJECT)
    extracted_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    total_rows = 0
    series_with_data = 0

    for series_id in SERIES_IDS:
        log.info("[%s] Checking watermark ...", series_id)
        watermark = get_watermark(bq_client, series_id)

        if watermark:
            log.info("[%s] Watermark: %s — fetching from that date.", series_id, watermark)
        else:
            log.info("[%s] No watermark — full historical load.", series_id)

        raw_obs = fetch_observations(series_id, observation_start=watermark)

        if not raw_obs:
            log.info("[%s] No observations returned. Skipping.", series_id)
            # Respect rate limit even on empty responses
            time.sleep(0.6)
            continue

        rows = transform_observations(series_id, raw_obs, extracted_at)
        append_to_bigquery(bq_client, rows)

        total_rows += len(rows)
        series_with_data += 1
        log.info("[%s] Loaded %d rows.", series_id, len(rows))

        # Rate limit: ~0.6s gap gives ~100 req/min headroom under the 120/min cap
        time.sleep(0.6)

    log.info(
        "fred_economic extraction complete. Series with data: %d/%d. Total rows: %d.",
        series_with_data, len(SERIES_IDS), total_rows,
    )


if __name__ == "__main__":
    main()
