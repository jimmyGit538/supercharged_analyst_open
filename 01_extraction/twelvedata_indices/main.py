import os
import requests
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

# S&P 500 proxy (IVV ETF), Nasdaq Composite (ONEQ ETF), Dow Jones proxy (DIA ETF)
SYMBOLS = ["IVV", "ONEQ", "DIA"]
INTERVAL = "1day"
BASE_URL = "https://api.twelvedata.com"
BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")
BQ_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.twelvedata_indices_daily"
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

if not TWELVEDATA_API_KEY:
    raise EnvironmentError("TWELVEDATA_API_KEY is not set")
if not BQ_PROJECT:
    raise EnvironmentError("BQ_PROJECT_EXTRACTION is not set")

BQ_METADATA_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.twelvedata_symbols_metadata"

SCHEMA = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("open", "FLOAT64"),
    bigquery.SchemaField("high", "FLOAT64"),
    bigquery.SchemaField("low", "FLOAT64"),
    bigquery.SchemaField("close", "FLOAT64"),
    bigquery.SchemaField("volume", "INT64"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

METADATA_SCHEMA = [
    bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("instrument_type", "STRING"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("exchange", "STRING"),
    bigquery.SchemaField("mic_code", "STRING"),
    bigquery.SchemaField("country", "STRING"),
    bigquery.SchemaField("figi_code", "STRING"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def get_watermark(client: bigquery.Client, symbol: str) -> str | None:
    """Return the latest date already in BigQuery for this symbol, or None for a full load."""
    query = f"""
        SELECT MAX(date) AS max_date
        FROM `{BQ_TABLE}`
        WHERE symbol = '{symbol}'
    """
    try:
        result = client.query(
            query,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10 * 1024 * 1024),
        ).result()
        row = next(iter(result))
        return str(row.max_date) if row.max_date else None
    except Exception:
        return None  # table doesn't exist yet — full load


def extract(symbol: str, start_date: str | None) -> tuple[list[dict], str | None]:
    """Return (values, instrument_type). instrument_type comes from the meta block."""
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": 5000,
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
    }
    if start_date:
        next_day = str(date.fromisoformat(start_date) + timedelta(days=1))
        params["start_date"] = next_day

    response = requests.get(f"{BASE_URL}/time_series", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        msg = data.get("message", "")
        if "No data is available" in msg:
            print(f"[extract] {symbol}: no new data available — non-trading period.")
            return [], data.get("meta", {}).get("type")
        raise RuntimeError(f"Twelvedata API error ({symbol}): {msg}")

    values = data.get("values", [])
    instrument_type = data.get("meta", {}).get("type")
    print(f"[extract] {symbol}: fetched {len(values)} rows (type={instrument_type})")
    return values, instrument_type


def extract_metadata(symbol: str, instrument_type: str | None) -> dict | None:
    """Fetch reference metadata for a symbol from /etf or /stocks, US primary listing."""
    extracted_at = datetime.now(timezone.utc).isoformat()

    endpoint_types = {"/etf": "ETF", "/stocks": "Common Stock"}
    for endpoint, default_type in endpoint_types.items():
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        us_listings = [r for r in data if r.get("country") == "United States"]
        if us_listings:
            row = us_listings[0]
            print(f"[metadata] {symbol}: found via {endpoint}")
            return {
                "symbol": symbol,
                "name": row.get("name"),
                "instrument_type": instrument_type or default_type,
                "currency": row.get("currency"),
                "exchange": row.get("exchange"),
                "mic_code": row.get("mic_code"),
                "country": row.get("country"),
                "figi_code": row.get("figi_code"),
                "extracted_at": extracted_at,
            }

    print(f"[metadata] {symbol}: no US listing found in /etf or /stocks")
    return None


def transform(symbol: str, values: list[dict]) -> list[dict]:
    extracted_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "date": row["datetime"],
            "symbol": symbol,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
            "extracted_at": extracted_at,
        }
        for row in values
    ]


def load(client: bigquery.Client, records: list[dict]) -> None:
    if not records:
        print("[load] No new records to load.")
        return

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition="WRITE_APPEND",
    )
    job = client.load_table_from_json(records, BQ_TABLE, job_config=job_config)
    job.result()
    print(f"[load] Appended {len(records)} rows into {BQ_TABLE}")


def load_metadata(client: bigquery.Client, records: list[dict]) -> None:
    if not records:
        print("[load_metadata] No metadata records to load.")
        return

    job_config = bigquery.LoadJobConfig(
        schema=METADATA_SCHEMA,
        write_disposition="WRITE_TRUNCATE",
    )
    job = client.load_table_from_json(records, BQ_METADATA_TABLE, job_config=job_config)
    job.result()
    print(f"[load_metadata] Wrote {len(records)} rows into {BQ_METADATA_TABLE}")


def main():
    client = bigquery.Client(project=BQ_PROJECT)
    all_records = []
    metadata_records = []

    for symbol in SYMBOLS:
        watermark = get_watermark(client, symbol)
        print(f"[watermark] {symbol}: last loaded date = {watermark or 'none — full load'}")

        values, instrument_type = extract(symbol, start_date=watermark)
        if values:
            records = transform(symbol, values)
            all_records.extend(records)
            print(f"[transform] {symbol}: latest date = {records[0]['date']}")

        meta = extract_metadata(symbol, instrument_type)
        if meta:
            metadata_records.append(meta)

    load(client, all_records)
    load_metadata(client, metadata_records)
    print(f"[main] Done. Price rows loaded: {len(all_records)}, metadata rows: {len(metadata_records)}")


if __name__ == "__main__":
    main()
