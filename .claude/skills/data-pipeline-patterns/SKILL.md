---
name: data-pipeline-patterns
description: >
  Expert guidance on designing data pipelines, specifically choosing between full refresh
  and incremental loading strategies. 
  
Use this skill whenever a user asks about:
  ETL/ELT design, data pipeline architecture, loading strategies, dbt model configuration,
  incremental vs full refresh tradeoffs, handling late-arriving data, upserts, merges,
  backfilling, warehouse cost optimization, or how to load data from a source system into
  a target table. 
  
Trigger even for adjacent questions like "my pipeline is too slow" or
  "my Snowflake bill is too high" — these often trace back to pipeline pattern choices.
  
Also trigger when a user shares a schema or describes a source system and asks how
  to build a pipeline for it.
  
  Also trigger when determining:
  How to transform data and build dbt models based on the RAW data passed to you from the data-extractor agent,
  How to transform data stored in the 01_extraction directory and prepare it for either data warehouse dbt models OR data mart dbt models.
---

# Data Pipeline Patterns: Full Refresh vs Incremental

## Decision Framework

Before recommending a pattern, gather the following about the source data:

1. **Does the source have reliable timestamps?** (`created_at`, `updated_at`, etc. that are actually populated and maintained)
2. **Can rows be updated or deleted?** Or is it append-only?
3. **How large is the dataset?** (rows, GB — and how fast is it growing?)
4. **How fresh does the target data need to be?** (hourly, daily, near-real-time?)
5. **Does the platform support MERGE?** (Some older Redshift configs don't; some lakehouses use insert+overwrite instead)

If the user hasn't answered these, ask before recommending a pattern.

---

## Pattern 1: Full Refresh

### What it is
Drop and recreate the entire target table on every pipeline run. Uses `CREATE OR REPLACE` (SQL), `materialized = 'table'` (dbt), or equivalent.

### When to use
- Dataset is small (typically under a few GB)
- No reliable change-tracking columns on the source
- Simplicity is valued over efficiency
- Backfill behavior needs to be dead-simple (just rerun)
- Data can be deleted from the source and those deletes need to propagate

### Tradeoffs
| Pro | Con |
|-----|-----|
| Dead simple to implement | Compute cost scales with full table size |
| Handles deletes automatically | Slow on large tables |
| Easy to backfill (just rerun) | Can cause downstream query failures during rebuild |
| No risk of stale/duplicate rows | Not suitable for large or frequently refreshed tables |

### WAP Pattern (Write-Audit-Publish)
For safer full refreshes, stage before promoting to production:

```sql
-- 1. WRITE: build into a staging table
CREATE OR REPLACE TABLE staging.orders AS
SELECT * FROM raw.orders;

-- 2. AUDIT: run checks
-- e.g., row count >= yesterday's count, no nulls on key columns, no duplicate PKs

-- 3. PUBLISH: only if checks pass
CREATE OR REPLACE TABLE analytics.orders AS
SELECT * FROM staging.orders;
```

---

## Pattern 2: Incremental — Date/ID Append

### What it is
Only load rows that are new since the last successful run, using a watermark (max date or max ID already in the target).

### When to use
- Source has a reliable, always-populated timestamp or monotonic ID
- Rows are append-only (never updated or deleted)
- Table is large or growing fast

### ID-based append
```sql
-- Faster, but assumes IDs always arrive in order
INSERT INTO analytics.orders
SELECT * FROM raw.orders
WHERE id > (SELECT MAX(id) FROM analytics.orders);

-- Safer (handles out-of-order IDs), but more expensive
INSERT INTO analytics.orders
SELECT * FROM raw.orders
WHERE id NOT IN (SELECT id FROM analytics.orders);
```

### Date-based append
```sql
-- Pure append (fast, but brittle with late-arriving data)
INSERT INTO analytics.orders
SELECT * FROM raw.orders
WHERE order_date > (SELECT MAX(order_date) FROM analytics.orders);
```

### Lookback window (recommended for production)
Handles late-arriving records and partial failures:

```sql
-- Delete the overlap window first
DELETE FROM analytics.orders
WHERE order_date >= CURRENT_DATE - INTERVAL '2 days';

-- Re-insert covering the same window
INSERT INTO analytics.orders
SELECT * FROM raw.orders
WHERE order_date >= CURRENT_DATE - INTERVAL '2 days';
```

> **Warning**: The lookback delete+insert is NOT atomic in most warehouses. If the insert fails after the delete, you have a gap. Run both steps in a transaction, or use the WAP pattern.

---

## Pattern 3: Incremental — Upsert / Merge

### What it is
Compare incoming rows to the target on a unique key. Insert new rows, update existing rows that have changed.

### When to use
- Source rows can be updated (mutable records)
- You need to propagate changes without full rebuilds
- You have a reliable unique key per row

### SQL MERGE example
```sql
MERGE INTO analytics.customers AS target
USING staging.customers AS source
  ON target.customer_id = source.customer_id
WHEN MATCHED THEN
  UPDATE SET
    target.email = source.email,
    target.status = source.status,
    target.updated_at = source.updated_at
WHEN NOT MATCHED THEN
  INSERT (customer_id, email, status, updated_at)
  VALUES (source.customer_id, source.email, source.status, source.updated_at);
```

### If MERGE is unavailable (e.g., some Redshift configs)
```sql
-- Delete matched rows, then re-insert
DELETE FROM analytics.customers
WHERE customer_id IN (SELECT customer_id FROM staging.customers);

INSERT INTO analytics.customers
SELECT * FROM staging.customers;
```

---

## Pattern 4: Aggregation / Correction Records

### What it is
Source system never updates or deletes rows. Instead, it appends correction rows (positive or negative adjustments). Common in finance, insurance, and healthcare billing systems.

### When to use
- Source data is an immutable ledger (accounting, claims, billing)
- Corrections arrive as new rows, not updates

### Example
```sql
-- Sum all rows per account — corrections cancel out the original
SELECT account_id, SUM(amount) AS net_amount
FROM raw.transactions
GROUP BY account_id;
```

> Always verify before assuming append-only: check whether the source *actually* populates `updated_at`, and whether correction rows exist in the data.

---

## Key Warnings & Common Pitfalls

- **Unreliable timestamps**: Confirm `updated_at` is actually populated before building an incremental pipeline on it. Query `SELECT COUNT(*) FROM table WHERE updated_at IS NULL`.
- **Deletes don't propagate in incremental pipelines**: If the source deletes a row, incremental patterns won't remove it from the target unless you handle it explicitly (soft deletes, periodic full refresh, or CDC).
- **Late-arriving data**: Pure date-append with no lookback window will miss records that arrive after the pipeline runs. Use a 1–3 day lookback for safety.
- **Platform constraints**: Know whether your warehouse supports `MERGE`, `INSERT OVERWRITE`, or partition-based overwrite before designing the pattern.
- **Backfilling incremental pipelines**: Requires careful watermark management. For large backfills, consider temporarily switching to a chunked full refresh.

---

## Quick Reference: Pattern Selection

| Scenario | Recommended Pattern |
|----------|-------------------|
| Small table, no timestamps, need simplicity | Full Refresh |
| Large append-only table with monotonic ID | ID-based Append |
| Large table with reliable timestamps, append-only | Date Append with Lookback |
| Mutable records, reliable unique key | Merge / Upsert |
| Immutable ledger with correction rows | Aggregation |
| Need deletes to propagate, large table | Merge with delete clause OR periodic full refresh |

