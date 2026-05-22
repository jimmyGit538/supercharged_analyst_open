---
name: twelvedata-api
description: >
  Twelvedata API reference. Auto-invoke when writing code that calls the
  Twelvedata API, building Twelvedata extractors, or answering questions about
  Twelvedata endpoints, parameters, or response shapes.
---

# Twelvedata API

**Full LLM-friendly reference:** https://twelvedata.com/docs/llms.txt

When this skill is loaded, fetch the above URL and use it as the authoritative
reference for all endpoint names, parameters, response schemas, and error codes.

## Key Facts (quick reference)

**Base URL:** `https://api.twelvedata.com`

**Auth:** `apikey` query parameter on every request.

**Used in this project:**
- Extraction job: `01_extraction/twelvedata_indices/main.py`
- Symbols: `IVV` (S&P 500 proxy), `ONEQ` (Nasdaq Composite — Fidelity Nasdaq Composite Index Fund), `DIA` (Dow Jones proxy)
- BQ table: `YOUR_GCP_PROJECT_ID.raw.twelvedata_indices_daily`
- Secret Manager secret: `TWELVEDATA_API_KEY`
- Env var: `TWELVEDATA_API_KEY`

## Time Series (primary endpoint used)

```
GET /time_series
  ?symbol=SPY
  &interval=1day        # 1min, 5min, 15min, 30min, 45min, 1h, 2h, 4h, 1day, 1week, 1month
  &outputsize=5000      # max rows per call
  &start_date=YYYY-MM-DD
  &apikey=KEY
  &format=JSON
```

**Response shape:**
```json
{
  "meta": { "symbol": "SPY", "interval": "1day", ... },
  "values": [
    { "datetime": "2024-01-15", "open": "...", "high": "...", "low": "...", "close": "...", "volume": "..." }
  ],
  "status": "ok"
}
```

Values are returned **newest-first**. All numeric fields are strings — cast them explicitly (`float()`, `int()`).

**Error response:**
```json
{ "status": "error", "code": 400, "message": "No data is available on the specified dates." }
```
"No data is available" means no trading activity for the requested period (weekend, holiday). Treat as a clean exit — do not raise.

## No-New-Data Handling

```python
if data.get("status") == "error":
    msg = data.get("message", "")
    if "No data is available" in msg:
        print("[extract] No new data available — non-trading period.")
        return []
    raise RuntimeError(f"Twelvedata API error: {msg}")
```
