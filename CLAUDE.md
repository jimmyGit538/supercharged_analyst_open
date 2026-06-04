# Supercharged Analyst — Claude Instructions

Full strategy and architecture reference: `docs/architecture.md`

## Project Overview

GCP-native modern data stack for a small analytics team. The goal is to extract, store, transform, and analyse data with minimal engineering overhead, powered by AI agents that write code, manage repositories, and surface insights automatically.

## Directory Structure

```
01_extraction/                          # One subdirectory per data source (main.py, requirements.txt, Dockerfile)
02_dbt/                                 # dbt Core project (staging views → mart tables in BigQuery)
  Dockerfile                            # Docker image for the dbt runner
  dbt_project.yml                       # dbt project configuration
  packages.yml                          # dbt package dependencies
  profiles.yml                          # dbt connection profiles
  requirements.txt                      # Python dependencies for dbt runner
  macros/
    generate_schema_name.sql            # Custom schema name macro
  models/
    1_staging_warehouses/               # Staging views from raw warehouse sources
    2_warehouses/                       # Cleaned warehouse tables
    3_staging_marts/                    # Staging views feeding mart layer
    4_marts/                            # Fact and dimension mart tables
  tests/                                # dbt tests
infra/                                  # GCP infrastructure (Terraform + legacy bootstrap scripts)
  terraform/                            # Terraform IaC — primary infra management
    main.tf                             # Provider config, GCP API enablement
    variables.tf                        # Input variables (project_id, region, sources map)
    locals.tf                           # Auto-generates Cloud Run Jobs from sources map
    sources.tf                          # Cloud Run Jobs + Cloud Scheduler (for_each)
    workflows.tf                        # Cloud Workflows (references YAML via file())
    iam.tf                              # 5 service accounts, IAM bindings, WIF
    bigquery.tf                         # BigQuery datasets
    artifact_registry.tf                # Docker image repository
    secrets.tf                          # Secret Manager validation
    outputs.tf                          # Useful outputs (SA emails, job names, WIF provider)
    terraform.tfvars.example            # Template — copy to terraform.tfvars and fill in values
    import.sh                           # One-time import of existing GCP resources into state
  workflows/                            # Cloud Workflow YAML definitions
    example_pipeline.yaml               # Example Cloud Workflow orchestrating Cloud Run Jobs in sequence
    create_jobs.sh                      # Legacy: manual job creation (superseded by Terraform)
    deploy.sh                           # Legacy: manual workflow deployment (superseded by Terraform)
  setup.sh                              # Legacy: one-time GCP bootstrap (superseded by Terraform)
  agent_registry/                       # Registry that snapshots agent/skill changes to BigQuery
    schema.sql                          # DDL: agent_snapshots, skill_snapshots tables
    loader.py                           # Runtime loader — reads .claude/ files, auto-snapshots on change
    snapshot.py                         # Snapshot engine — append-only audit log and diff utility
    manage.py                           # CLI: sync, diff, list commands
    hook.py                             # Claude Code hook integration for auto-snapshotting
    parser.py                           # Parses .claude/ markdown files into structured records
    deploy.sh                           # Deploys the agent registry to GCP
    example_agent.py                    # Reference implementation for bootstrapping an agent from the registry
    requirements.txt                    # Dependencies: google-cloud-bigquery, anthropic, python-dotenv
docs/                                   # Strategy documents and reference material
  architecture.md                       # Full strategy and architecture reference
  system_overview.svg                   # System architecture diagram
scripts/                                # Utility shell scripts
  setup.sh                              # One-time environment/project setup script
.github/workflows/                      # CI only: lint + docker build+push (NOT pipeline scheduling)
  ci.yml                                # Lint, test, and Docker build+push on PR/push
  deploy.yml                            # Deployment workflow
```

## Stack

| Layer | Tool |
|---|---|
| Extraction | Python scripts, containerised with Docker |
| Container Registry | GCP Artifact Registry |
| Scheduling | Cloud Scheduler → Cloud Run Jobs |
| Orchestration | Cloud Workflows |
| Warehouse | BigQuery |
| Transformation | dbt Core |
| Infrastructure | Terraform (GCP provider) |
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

**Cloud Run Jobs**
- Pattern: `{pipeline}-{stage}-{frequency}` — e.g., `indices-extract-daily`, `indices-dbt-warehouse-daily`
- `pipeline` is the data source / domain (e.g. `indices`, `salesforce`, `stripe`)
- `frequency` is the run cadence: `hourly` | `daily` | `weekly` | `monthly` | `quarterly` | `yearly`
- `stage` describes the job's position in the pipeline:

| `stage` value | dbt layer | What it does | Reads from | Writes to |
|---|---|---|---|---|
| `extract` | — | Pulls data from the source system | External API | `raw` dataset |
| `dbt-stg-warehouse` | `1_staging_warehouses` | Builds staging views from raw sources | `raw` dataset | `stg_warehouses` dataset |
| `dbt-warehouse` | `2_warehouses` | Seeds reference CSVs + builds warehouse tables | `stg_warehouses` dataset | `warehouses` dataset |
| `dbt-stg-marts` | `3_staging_marts` | Builds staging views feeding the mart layer | `warehouses` dataset | `stg_marts` dataset |
| `dbt-mart` | `4_marts` | Builds fact and dimension tables | `stg_marts` dataset | `marts` dataset |

Examples:
- `indices-extract-daily` — daily extraction of index data from Twelvedata into `raw`
- `indices-dbt-stg-warehouse-daily` — builds staging views from raw indices data
- `indices-dbt-warehouse-daily` — seeds metadata + builds warehouse tables for indices
- `indices-dbt-stg-marts-daily` — builds staging views feeding the indices mart layer
- `indices-dbt-mart-daily` — builds fact and dimension tables for Looker Studio

**BigQuery datasets**
- `raw` — landing zone for extraction jobs (Data Editor access only)
- `staging` — dbt staging views
- `warehouses` - dbt warehouse tables (cleaned extraction)
- `marts` — dbt mart tables (source for Looker Studio)

## Infrastructure (Terraform)

All GCP infrastructure is managed by Terraform in `infra/terraform/`. This is the source of truth for infrastructure — the legacy shell scripts (`setup.sh`, `create_jobs.sh`, `deploy.sh`) are retained as reference but superseded by Terraform.

**Adding a new data source:**

> Before starting any work on a new data source, invoke the `add-data-source` skill (`/add-data-source`) to complete the intake process. No code should be written until all intake questions are answered and API research is complete.

1. Create `01_extraction/<source>/main.py`, `requirements.txt`, `Dockerfile`
2. Create `infra/workflows/<source>_pipeline.yaml` (Cloud Workflow definition)
3. Add one entry to `terraform.tfvars` in the `sources` map
4. Run `terraform plan` to review, then `terraform apply`
5. Push Docker images via GitHub Actions CI

Terraform auto-generates 5 Cloud Run Jobs per source from the `sources` map:
- 1 extraction job (source-specific Docker image)
- 4 dbt jobs (shared `dbt-runner` image, stage-specific commands)

**Service accounts** (5 total, managed in `iam.tf`):

| Account | Purpose |
|---|---|
| `extraction-runner` | Runs extraction Cloud Run Jobs, writes to `raw` dataset |
| `dbt-runner` | Runs dbt Cloud Run Jobs, reads `raw`, writes `staging`/`warehouses`/`marts` |
| `github-actions-ci` | Pushes Docker images to Artifact Registry (via WIF, no keys) |
| `workflow-runner` | Executes Cloud Workflows, invokes Cloud Run Jobs |
| `scheduler-runner` | Triggers Cloud Workflows on schedule |

**BigQuery dataset access** is managed by `infra/setup.sh` (legacy format). Terraform manages the datasets themselves but not the access entries, due to provider limitations with `google_bigquery_dataset_access` import.

**Terraform state** is local. Before team collaboration or CI/CD for infrastructure, migrate to a GCS remote backend.

## Agent Registry

The `infra/agent_registry/` package tracks every change to agent and skill definitions as an append-only audit log in BigQuery.

**Source of truth:** `.md` files in `.claude/` — edit these in your IDE.
- Agents: `.claude/agents/<name>.md`
- Skills: `.claude/skills/<name>/SKILL.md`

**BigQuery role:** append-only snapshot history (`agent_snapshots`, `skill_snapshots`) — queryable audit log, not the live source of truth.

**How it works:**
1. `schema.sql` provisions two BigQuery tables: `agent_snapshots`, `skill_snapshots`.
2. `loader.py` reads definitions from `.claude/` at agent startup. If the file content has changed since the last snapshot, it automatically writes a new snapshot to BigQuery — no manual step needed.
3. `snapshot.py` is the low-level writer; it also exposes `diff` and `list_snapshots` for querying history.
4. `manage.py sync` iterates all `.claude/` files and triggers the same auto-snapshot logic — useful for bulk syncs or CI.

**Rules:**
- Edit agent and skill definitions in `.claude/` only — never write directly to BigQuery snapshot tables.
- Use `performance_tag` in snapshots when A/B testing prompt variants so results can be queried and compared.

## Hard Rules

- **Never use GitHub Actions as a pipeline scheduler.** GitHub Actions is for CI/CD only (lint, test, docker build+push).
- **Never use static credentials or exported service account keys.** Always use Workload Identity Federation or service account impersonation.
- **All infrastructure changes must go through Terraform** in `infra/terraform/` — no manual console changes or ad-hoc gcloud commands. Run `terraform plan` before `terraform apply`.
- **All Claude Code-generated code must go through a GitHub PR** before merging to main. Human review is the mandatory checkpoint.
- **BigQuery cost controls:** always use column pruning, table partitioning, and `maximum_bytes_billed` limits.
- **Never hardcode secrets or real infrastructure values.** Never include real credentials, project IDs, account numbers, or internal URLs in any committed file — regardless of repo visibility. Always use placeholder values (e.g. `YOUR_PROJECT_ID`) or environment variable references (`${{ secrets.X }}`, `os.getenv("X")`). Secrets belong in `.env` (gitignored) or GitHub Actions secrets — never in code.
