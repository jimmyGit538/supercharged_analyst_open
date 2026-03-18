# Supercharged Analyst — Claude Instructions

Full strategy and architecture reference: `docs/supercharged_analyst_plan.md`

## Project Overview

GCP-native modern data stack for a small analytics team. The goal is to extract, store, transform, and analyse data with minimal engineering overhead, powered by AI agents that write code, manage repositories, and surface insights automatically.

## Directory Structure

```
01_extraction/                          # One subdirectory per data source (main.py, requirements.txt, Dockerfile)
02_dbt/                                 # dbt Core project (staging views → mart tables in BigQuery)
  models/
    1_staging_warehouses/               # Staging views from raw warehouse sources
    2_warehouses/                       # Cleaned warehouse tables
    3_staging_marts/                    # Staging views feeding mart layer
    4_marts/                            # Fact and dimension mart tables
  tests/                                # dbt tests
infra/                                  # GCP bootstrap scripts, gcloud / Terraform configs
  agent_registry/                       # BigQuery-backed registry for agent and skill definitions
    schema.sql                          # DDL: agents, skills, agent_snapshots, skill_snapshots tables
    loader.py                           # Runtime loader — pulls live definitions from BigQuery at startup
    snapshot.py                         # Snapshot engine — append-only audit log and diff utility
    manage.py                           # CLI: upsert, snapshot, diff, list commands
    example_agent.py                    # Reference implementation for bootstrapping an agent from the registry
    requirements.txt                    # Dependencies: google-cloud-bigquery, anthropic, python-dotenv
docs/                                   # Strategy documents and reference material
.github/workflows/                      # CI only: lint + docker build+push (NOT pipeline scheduling)
```

## Stack

| Layer | Tool |
|---|---|
| Extraction | Python scripts, containerised with Docker |
| Container Registry | GCP Artifact Registry |
| Scheduling | Cloud Scheduler → Cloud Run Jobs |
| Warehouse | BigQuery |
| Transformation | dbt Core |
| Observability | Cloud Logging + Cloud Monitoring |
| Version Control | GitHub |
| CI/CD | GitHub Actions (CI only) |
| BI | Looker Studio |
| AI | Claude Code + Claude.ai |

## Conventions

**Extraction jobs**
- One subdirectory per source under `01_extraction/` (e.g. `01_extraction/salesforce/`)
- Each contains: `main.py`, `requirements.txt`, `Dockerfile`
- Dockerfile template:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install -r requirements.txt
  COPY main.py .
  CMD ["python", "main.py"]
  ```

**dbt models**
- Staging models: `02_dbt/models/1_staging_warehouses/stg_<source>__<entity>.sql`, `02_dbt/models/3_staging_marts/stg_<source>__<entity>.sql`  — materialised as views
- Warehouse models: `02_dbt/models/2_warehouses/<source>_<name>.sql` — materialised as tables
- Mart models: `02_dbt/models/4_marts/fct_<name>.sql` or `dim_<name>.sql`

- All models must have column-level documentation and dbt tests

**BigQuery datasets**
- `raw` — landing zone for extraction jobs (Data Editor access only)
- `staging` — dbt staging views
- `warehouses` - dbt warehouse tables (cleaned extraction)
- `marts` — dbt mart tables (source for Looker Studio)

## Agent Registry

The `infra/agent_registry/` package is the **central nervous system for all AI agents in this project**. BigQuery is the single source of truth for every agent and skill definition — no agent should hardcode its own system prompt or load instructions from a local file at runtime.

**Why it exists:**
- Agents and skills evolve frequently. Without a registry, definitions drift across files, branches, and conversations with no audit trail.
- BigQuery gives us versioned, queryable, durable storage with the same cost controls and access patterns as the rest of the stack.
- Snapshots enable A/B testing of agent prompts and rollback to any prior version without a code deploy.

**How it works:**
1. `schema.sql` provisions four BigQuery tables: `agents`, `skills`, `agent_snapshots`, `skill_snapshots`.
2. `manage.py` is the CLI for day-to-day operations — upsert a definition from a markdown file, snapshot the current state, diff two versions, or list history.
3. `loader.py` is imported by every agent at startup to pull its live definition from BigQuery. Cached loading is available for high-frequency agents.
4. `snapshot.py` writes append-only audit records on every change and exposes unified diffs between any two snapshots.

**Rules:**
- Every agent and skill definition must be registered here before it is used in production.
- Changes to definitions must go through `manage.py upsert` (not direct BigQuery edits) so that snapshots are captured automatically.
- Use `performance_tag` in snapshots when A/B testing prompt variants so results can be queried and compared.

## Hard Rules

- **Never use GitHub Actions as a pipeline scheduler.** GitHub Actions is for CI/CD only (lint, test, docker build+push).
- **Never use static credentials or exported service account keys.** Always use Workload Identity Federation or service account impersonation.
- **All infrastructure changes must be codified** in `infra/` — no manual console changes.
- **All Claude Code-generated code must go through a GitHub PR** before merging to main. Human review is the mandatory checkpoint.
- **BigQuery cost controls:** always use column pruning, table partitioning, and `maximum_bytes_billed` limits.
