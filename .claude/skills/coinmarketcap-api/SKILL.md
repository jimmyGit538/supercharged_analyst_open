---
name: coinmarketcap-api
description: >
  CoinMarketCap API reference. Auto-invoke when writing code that calls the
  CoinMarketCap API, building CoinMarketCap extractors, or answering questions
  about CoinMarketCap endpoints, parameters, or response shapes.
  Do NOT load for general cryptocurrency discussions unrelated to the CMC API.
---

# CoinMarketCap API

**Full API reference:** https://coinmarketcap.com/api/documentation/v1/

When this skill is loaded, refer to the above URL as the authoritative reference
for all endpoint names, parameters, response schemas, and rate limits.

## Key Facts (quick reference)

**Base URL:** `https://pro-api.coinmarketcap.com/v1`

**Auth:** `X-CMC_PRO_API_KEY` request **header** on every request (not a query param).

**Used in this project:**
- Extraction job: `01_extraction/coin_market_cap/main.py`
- BQ tables: `raw.coinmarketcap_categories`, `raw.coinmarketcap_category_coins`, `raw.coinmarketcap_coin_metadata`, `raw.coinmarketcap_quotes_daily`
- Secret Manager secret: `COINMARKETCAP_API_KEY`
- Env var: `COINMARKETCAP_API_KEY`

## Endpoints Used in This Project

### 1. List All Categories

```
GET /cryptocurrency/categories
  ?start=1
  &limit=5000
```

**Response shape:**
```json
{
  "status": { "timestamp": "...", "error_code": 0, "error_message": null },
  "data": [
    { "id": "605e2ce9d41eae1066535f7c", "name": "DeFi", "num_tokens": 432, "avg_price_change": 1.23,
      "market_cap": 45000000000, "market_cap_change": 2.1, "volume": 3000000000, "volume_change": -0.5,
      "last_updated": "2024-01-15T..." }
  ]
}
```

### 2. Coins in a Category

```
GET /cryptocurrency/category
  ?id={category_id}
  &limit=1000
  &start=1
```

**Response shape:**
```json
{
  "status": { "error_code": 0 },
  "data": {
    "id": "605e2ce9d41eae1066535f7c",
    "name": "DeFi",
    "coins": [
      { "id": 1, "name": "Bitcoin", "symbol": "BTC", "slug": "bitcoin", "cmc_rank": 1, ... }
    ]
  }
}
```

### 3. Coin Metadata (batch up to 100 IDs per call)

```
GET /cryptocurrency/info
  ?id=1,1027,5426     # comma-separated CMC IDs
```

**Response shape:**
```json
{
  "status": { "error_code": 0 },
  "data": {
    "1": {
      "id": 1, "name": "Bitcoin", "symbol": "BTC", "slug": "bitcoin",
      "description": "Bitcoin is a decentralized...",
      "category": "coin",
      "tags": ["mineable", "pow", "sha-256"],
      "urls": { "website": ["https://bitcoin.org"], "twitter": ["https://twitter.com/bitcoin"] }
    }
  }
}
```

### 4. Daily Quotes Historical (incremental)

Note: `/cryptocurrency/ohlcv/historical` requires a higher plan tier (403 on Hobbyist).
Use `/cryptocurrency/quotes/historical` instead — available on Hobbyist, returns price/volume/market_cap/% changes.

```
GET /cryptocurrency/quotes/historical
  ?id={cmc_id}
  &time_start=YYYY-MM-DD
  &time_end=YYYY-MM-DD
  &interval=daily
  &convert=USD
```

**Response shape:**
```json
{
  "status": { "error_code": 0 },
  "data": {
    "id": 1,
    "name": "Bitcoin",
    "symbol": "BTC",
    "quotes": [
      {
        "timestamp": "2024-01-15T00:00:00.000Z",
        "quote": {
          "USD": {
            "price": 42800.0,
            "volume_24h": 28000000000.0,
            "market_cap": 835000000000.0,
            "percent_change_1h": -0.2,
            "percent_change_24h": 1.5,
            "percent_change_7d": 3.8,
            "timestamp": "2024-01-15T00:00:00.000Z"
          }
        }
      }
    ]
  }
}
```

## Error Handling Pattern

All CMC responses include a `status` block. Check `error_code` — 0 means success:

```python
headers = {"X-CMC_PRO_API_KEY": API_KEY, "Accept": "application/json"}
response = requests.get(url, params=params, headers=headers, timeout=30)
response.raise_for_status()
data = response.json()

status = data.get("status", {})
if status.get("error_code") != 0:
    raise RuntimeError(f"CMC API error ({status.get('error_code')}): {status.get('error_message')}")
```

## Rate Limits & Plan Constraints (Hobbyist/Startup Plan)

- ~333 credits/minute
- Each endpoint call costs 1 credit by default (some cost more — check docs)
- Add `time.sleep(0.2)` between per-coin calls to stay under the rate limit
- **Historical lookback: 12 months max** — `time_start` must be within the last 365 days; older dates return a 400 error
- `/cryptocurrency/ohlcv/historical` requires Standard tier or higher (returns 403 on Hobbyist) — use `/cryptocurrency/quotes/historical` instead
