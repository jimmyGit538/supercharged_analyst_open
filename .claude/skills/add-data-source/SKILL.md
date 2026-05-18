---
name: add-data-source
description: >
  Structured intake process for adding a new API or data source to the Supercharged Analyst pipeline.

  Invoke this skill whenever a user wants to:
  - Add a new data source, API, or integration to the pipeline
  - Build a new extractor (e.g. "add Stripe", "integrate HubSpot", "pull data from X")
  - Start a new extraction job or data pipeline for a source not yet in 01_extraction/
  - Connect to a new external API and load data into BigQuery

  Trigger on phrases like: "add a new data source", "new API", "new extractor", "integrate X API",
  "add X pipeline", "new data pipeline", "connect to X", "pull data from X", "start extracting from X".

  Do NOT invoke for: modifying an existing extractor, debugging an existing pipeline, or dbt-only work
  on a source that already has a working extraction job.
---

# Add Data Source — Intake Process

## CRITICAL: No code until intake is complete

When this skill fires, you MUST complete the full intake process before writing any code, creating any
files, or invoking any agents. Announce this to the user upfront.

Tell the user: "Before we build anything, I need to ask a few questions to make sure we extract the
right data and build the right models. I'll research the API details myself — I just need your input
on intent and business requirements."

---

## Step 1 — Ask Extraction Questions

Ask the user these questions. Wait for all answers before proceeding.

1. **Source name** — What should we call this data source? Use lowercase with underscores
   (e.g. `stripe`, `hubspot`, `coin_market_cap`). This name will be used for the directory,
   BigQuery table prefix, Cloud Run Job names, and Terraform key — it must be consistent everywhere.

2. **Use case and final goal** — What business questions should this data answer? What will you do
   with it in Looker Studio or downstream dbt models? Be as specific as possible — this determines
   which endpoints and fields are worth extracting.

3. **Scheduling cadence** — How often should this data be refreshed?
   Options: `hourly` / `daily` / `weekly` / `monthly` / `quarterly` / `yearly`

---

## Step 2 — Research the API (Claude does this autonomously)

After collecting the extraction answers, search the internet for the API's official documentation.
Determine the following without asking the user:

- **Endpoints to extract** — Based on the stated use case, identify which endpoints return the data
  needed. Prefer endpoints that return the most granular, reusable data over summary endpoints.
- **Response structure** — Path to the records array within the JSON response, field names, types,
  and nullability. Map each field to a BigQuery type (STRING, INT64, FLOAT64, DATE, TIMESTAMP, etc.).
- **Authentication method** — Use the most secure available option: prefer OAuth 2.0 or
  header-based API key (`Authorization: Bearer` or `X-API-Key`) over query parameter auth.
  Generate credential env var / Secret Manager secret names using the pattern
  `<SOURCE_NAME_UPPER>_API_KEY` (or `_CLIENT_ID` / `_CLIENT_SECRET` for OAuth).
- **Pagination mechanism** — cursor-based, offset+limit, page number, or link header. Note the
  field names and how to detect end-of-results.
- **Rate limits** — requests per minute/hour for the relevant plan tier. Build retry logic
  accordingly (exponential backoff, respect `Retry-After` headers).
- **Incremental strategy** — Based on the use case and anticipated data volume, decide:
  - If the API has a reliable `updated_at`, `created_at`, `date`, or cursor field → watermark-based
    incremental (append new rows only)
  - If rows can be updated without a reliable change signal → full refresh (WRITE_TRUNCATE)
  - If data volume is small and historical → full refresh
  - Document the chosen strategy and the watermark field name.
- **API quirks** — fields returned as wrong type, non-standard error shapes, how "no data
  available" is signaled (HTTP 404 vs empty array vs error message in body).

Summarize your research findings to the user before proceeding to the dbt questions.

---

## Step 3 — Ask dbt Questions

Ask the user these questions. Wait for all answers before proceeding.

1. **dbt layers needed** — Which layers should we build?
   - Staging warehouse only (`1_staging_warehouses`)
   - Through to warehouse tables (`1_staging_warehouses` + `2_warehouses`)
   - Full pipeline through to marts (all four layers)
   - Or a custom subset?

2. **Business logic and derived metrics** — Are there any custom business rules, calculated fields,
   ratios, or aggregations that must live in the dbt models? For example: revenue calculations,
   custom categorizations, period-over-period comparisons, blended metrics across sources.
   If none, say so and Claude will apply standard patterns.

3. **Join requirements** — Does this data need to join to any existing warehouse tables
   (e.g. `stripe_charges` joined to `salesforce_accounts` on `customer_id`)? If so, which tables
   and on which key? List the existing table names and join keys, or say "none".

---

## Step 4 — Determine dbt Design (Claude does this autonomously)

After collecting the dbt answers, determine the following without asking the user:

- **Data grain** — What does one row in the raw table represent? (e.g. one transaction, one event,
  one day per entity). Derive this from the API response structure identified in Step 2.
- **Primary key** — Which column(s) uniquely identify a row. Derive from the API docs and grain.
- **Data quality concerns** — Identify likely issues: nulls on key columns, duplicate risk from
  pagination overlap, type mismatches, late-arriving data. Document how each will be mitigated
  in staging models or dbt tests (not_null, unique, accepted_values).
- **Loading strategy per layer**:
  - Staging views: always `view` materialization, no strategy needed
  - Warehouse tables: match the extraction strategy — incremental if watermark-based,
    full refresh if WRITE_TRUNCATE; set `unique_key` for upserts
  - Mart tables: incremental with partitioning for large tables, full refresh for small dims
- **Partition and cluster fields** — For tables expected to be large:
  - Partition on a date field (usually the event/transaction date)
  - Cluster on the highest-cardinality filter column (e.g. `customer_id`, `coin_id`)
  - Base this decision on the user's stated use case and query patterns in Looker Studio.

Present a brief summary of these decisions to the user before handoff.

---

## Step 5 — Handoff

Compile all answers and research into two structured briefs, then hand off to the specialized agents.

**Order of execution:**
1. Invoke `data-extractor` agent first — the extraction job must exist and produce raw tables before
   dbt can reference them.
2. After `data-extractor` confirms the raw tables are created, invoke `dbt-modeler` with the dbt brief.

**Extraction brief must include:**
- Source name (the exact slug from Q1)
- Confirmed endpoints, response structure, field→BQ type mapping
- Auth method and credential env var names
- Pagination approach
- Rate limits and retry strategy
- Incremental strategy and watermark field (or full refresh justification)
- BigQuery target table names: `raw.<source>_<entity>`
- Scheduling cadence → Cloud Run Job naming suffix

**dbt brief must include:**
- Source name (same slug)
- Raw table name(s) as dbt sources
- Data grain and primary key
- dbt layers to build
- Data quality concerns and mitigations (as dbt tests)
- Business logic / derived metrics
- Join requirements and keys
- Loading strategy per layer (with unique_key if incremental)
- Partition and cluster fields

**Naming consistency check** — Before handing off, verify that the source name slug from Q1 is
used consistently across all of the following. If any mismatch is found, correct it:
- Directory: `01_extraction/<source>/`
- BigQuery tables: `raw.<source>_<entity>`
- Cloud Run Jobs: `<source>-extract-<cadence>`, `<source>-dbt-stg-warehouse-<cadence>`,
  `<source>-dbt-warehouse-<cadence>`, `<source>-dbt-stg-marts-<cadence>`, `<source>-dbt-mart-<cadence>`
- dbt model names: `stg_<source>__<entity>.sql`, `<source>_<name>.sql`, `fct_<name>.sql`
- Terraform `sources` map key in `terraform.tfvars`
- Workflow YAML: `infra/workflows/<source>_pipeline.yaml`

**Remind `data-extractor`** of the 5-step CLAUDE.md checklist:
1. Create `01_extraction/<source>/main.py`, `requirements.txt`, `Dockerfile`
2. Create `infra/workflows/<source>_pipeline.yaml`
3. Add one entry to `terraform.tfvars` in the `sources` map
4. Run `terraform plan` then `terraform apply`
5. Push Docker image via GitHub Actions CI

---

## Convention Quick Reference

| Artifact | Pattern |
|---|---|
| Extraction dir | `01_extraction/<source>/` |
| BQ raw tables | `raw.<source>_<entity>` |
| Extract job | `<source>-extract-<cadence>` |
| dbt jobs | `<source>-dbt-stg-warehouse-<cadence>`, `<source>-dbt-warehouse-<cadence>`, `<source>-dbt-stg-marts-<cadence>`, `<source>-dbt-mart-<cadence>` |
| dbt staging | `stg_<source>__<entity>.sql` (view, schema: staging) |
| dbt warehouse | `<source>_<name>.sql` (table, schema: warehouses) |
| dbt staging mart | `stg_<source>__<entity>.sql` (view, schema: staging) |
| dbt mart | `fct_<name>.sql` / `dim_<name>.sql` (table, schema: marts) |
| Workflow YAML | `infra/workflows/<source>_pipeline.yaml` |
| Terraform key | one entry in `terraform.tfvars` `sources` map |
