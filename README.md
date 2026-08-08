# Supercharged Analyst

A GCP-native modern data stack template for small analytics teams. Fork this repo, connect your data sources, and have a production-grade pipeline running in an afternoon — with Claude Code agents that write extraction code, dbt models, and infrastructure config for you.

## What you get

- **Containerised extraction jobs** — one Docker image per data source, running as Cloud Run Jobs
- **dbt transformation pipeline** — 4-layer model architecture (staging → warehouse → staging marts → marts) landing in BigQuery
- **Cloud Workflows orchestration** — 5-stage pipeline per source, triggered by Cloud Scheduler
- **Terraform-managed infrastructure** — all GCP resources declared as code, one config file to add a new source
- **GitHub Actions CI** — lints Python + SQL and builds every Docker image on each PR, then pushes to Artifact Registry on merge to `main`
- **Claude Code agents** — AI-powered `/add-data-source` skill that scaffolds a full new pipeline end-to-end
- **Agent Registry** — append-only BigQuery audit log of every agent and skill version

## Prerequisites

Before you start, make sure you have:

- [ ] A GCP project with billing enabled
- [ ] [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login && gcloud auth application-default login`)
- [ ] [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5 installed
- [ ] [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- [ ] Python 3.11+
- [ ] [Claude Code](https://claude.ai/code) CLI installed (`npm install -g @anthropic-ai/claude-code`)

## Quick Start

### 1. Fork and clone

```bash
# Fork this repo on GitHub, then clone your fork
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
```

### 2. Install pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your GCP project ID, service account email, and Anthropic API key
```

### 4. Enable GCP APIs (one-time)

```bash
export PROJECT_ID="your-gcp-project-id"

gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  workflows.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  --project "$PROJECT_ID"
```

### 5. Configure Terraform

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set project_id, region, github_repo
# Set sources = {} for now — comment out the fred-economic block. It references a
# Secret Manager secret you haven't created yet, and step 9 turns it back on.
```

### 6. Provision GCP infrastructure

```bash
terraform init
terraform plan    # review — expect service accounts, datasets, Artifact Registry
terraform apply
```

This creates:
- 5 service accounts with least-privilege IAM bindings
- Workload Identity Federation pool for GitHub Actions (no static keys)
- BigQuery datasets: `raw`, `stg_warehouses`, `warehouses`, `stg_marts`, `marts`, `agent_registry`
- Artifact Registry repository for Docker images

### 6a. Grant BigQuery dataset access

**Do not skip this step.** Terraform creates the datasets and the service accounts, but it
does *not* grant dataset-level access — the `google_bigquery_dataset_access` resource has
no usable import path, so those entries are owned by `infra/setup.sh` instead (see the
comment block in `infra/terraform/bigquery.tf`).

```bash
cd ../..                              # back to the repo root
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export GITHUB_REPO="your-org/your-repo"
bash infra/setup.sh
```

This grants `extraction-runner` WRITER on `raw`, and `dbt-runner` READER on `raw` plus
WRITER on `stg_warehouses`, `warehouses`, `stg_marts`, and `marts`.

Without it, everything deploys cleanly and then fails at *runtime*: extraction jobs return
a BigQuery 403 on their first write, and dbt jobs fail to read `raw`. Verify with:

```bash
bq show --format=prettyjson "${PROJECT_ID}:raw" | grep -A2 extraction-runner
```

### 7. Set up the Agent Registry (optional but recommended)

From the repo root, with `BQ_PROJECT` and `BQ_DATASET` set in your `.env`:

```bash
pip install -r infra/agent_registry/requirements.txt
bash infra/agent_registry/deploy.sh
```

The script provisions the BigQuery tables (substituting the `{PROJECT}`/`{DATASET}`
placeholders in `schema.sql`) and seeds the agent and skill definitions. Run it directly —
`schema.sql` is a template, not runnable SQL, and `manage.py` must be invoked as a module
from `infra/` (`python -m agent_registry.manage`), both of which the script handles.

### 8. Configure GitHub Actions CI

In your GitHub repo settings, add:

**Secrets:**
- `WORKLOAD_IDENTITY_PROVIDER` — from `terraform output wif_provider`
- `SERVICE_ACCOUNT` — from `terraform output ci_service_account`

**Variables:**
- `GCP_PROJECT_ID` — your GCP project ID
- `GCP_REGION` — e.g. `us-central1`

### 9. Run the reference source (FRED)

The template ships one complete, working source: **FRED** (Federal Reserve Economic Data)
— 118 US economic series (16 national macro indicators plus state-level house prices and
wages). It needs no paid account and exercises every layer of the stack, so run it first
to prove the pipeline before writing your own.

Create the API key secret **before** `terraform apply` — `infra/terraform/secrets.tf`
reads it as a `data` source, so the plan fails if it doesn't exist:

```bash
# Free key, instant: https://fredaccount.stlouisfed.org/apikeys
gcloud secrets create FRED_API_KEY --replication-policy="automatic" --project "$PROJECT_ID"
echo -n "your-fred-api-key" | gcloud secrets versions add FRED_API_KEY --data-file=- --project "$PROJECT_ID"
```

The secret name must be `FRED_API_KEY` — Terraform mounts secrets by matching the secret
name to the environment variable name.

Then enable the source and apply:

```bash
cd infra/terraform
# Uncomment the fred-economic block in terraform.tfvars (see terraform.tfvars.example)
terraform plan
terraform apply
```

This creates `fred-economic-extract-daily` plus the four dbt jobs, the `fred-economic-pipeline`
Cloud Workflow, and a daily 06:00 scheduler trigger. Once the images are in Artifact
Registry (see step 8), kick off a run:

```bash
gcloud workflows run fred-economic-pipeline --location="$REGION"
```

What lands: `raw.fred_economic_observations` → `stg_warehouses` → `warehouses` →
`stg_marts` → `marts.fct_fred_economic_indicators` and `marts.fct_fred_state_affordability`,
both ready to point Looker Studio at.

Extraction is incremental — each series carries its own date watermark, and the first run
backfills full history (hence `timeout = "3600s"` on the job).

### 10. Add your own data source

Open Claude Code in this repo and run:

```
/add-data-source
```

The skill walks you through:
1. API research and auth method
2. Extraction strategy (full refresh vs incremental)
3. Generates `01_extraction/<source>/main.py`, `Dockerfile`, `requirements.txt`
4. Generates all 4 layers of dbt models
5. Generates `infra/workflows/<source>_pipeline.yaml`
6. Adds the entry to `terraform.tfvars`

`01_extraction/fred_economic/` and the `fred_economic` dbt models are the reference
implementation to copy from.

After the skill completes, open a PR — CI lints and builds the Docker images. Once the PR
merges to `main`, the Deploy workflow pushes them to Artifact Registry.

## dbt Local Development

The dbt project lives in `02_dbt/` with a non-standard `profiles.yml` location. Use the `dev` target, which authenticates via your personal GCP credentials and writes to the `dbt_dev` BigQuery dataset (isolated from production).

**Prerequisites:**
- `BQ_PROJECT` set in your `.env`
- `gcloud auth application-default login` completed

**First-time setup** (handled by `scripts/setup.sh` if you ran it):
```bash
pip install -r 02_dbt/requirements.txt   # installs dbt-bigquery
dbt deps --profiles-dir 02_dbt --project-dir 02_dbt  # installs dbt_utils package
```

**Running dbt commands** (from the repo root):
```bash
# Verify BigQuery connection
dbt debug --profiles-dir 02_dbt --project-dir 02_dbt

# Compile SQL without executing
dbt compile --profiles-dir 02_dbt --project-dir 02_dbt

# Run all models
dbt run --profiles-dir 02_dbt --project-dir 02_dbt

# Run a single model
dbt run -s stg_fred_economic__observations --profiles-dir 02_dbt --project-dir 02_dbt

# Run tests
dbt test --profiles-dir 02_dbt --project-dir 02_dbt
```

If you source your `.env` (which sets `DBT_PROFILES_DIR=02_dbt`), you can drop `--profiles-dir`:
```bash
source .env
dbt run --project-dir 02_dbt
```

Models land in the `dbt_dev` dataset in BigQuery under your GCP project.

## Project Structure

```
01_extraction/          # One subdirectory per data source (main.py, Dockerfile, requirements.txt)
  fred_economic/        # Reference source — FRED economic series
02_dbt/                 # dbt Core project
  models/
    1_staging_warehouses/   # Staging views from raw          → stg_warehouses
    2_warehouses/           # Cleaned warehouse tables        → warehouses
    3_staging_marts/        # Staging views for mart layer    → stg_marts
    4_marts/                # Fact and dimension tables       → marts
infra/
  terraform/            # All GCP infrastructure as code
  workflows/            # Cloud Workflow YAML definitions (one per source)
  agent_registry/       # BigQuery audit log for agent/skill versions
.claude/
  agents/               # Claude Code subagent definitions
  skills/               # Claude Code skill definitions
docs/                   # Architecture and reference docs
.github/workflows/      # CI only — lint + Docker build/push
```

## Adding More Data Sources

Each new source follows the same pattern. The `/add-data-source` skill handles all of it, but the manual steps are:

1. Create `01_extraction/<source>/` with `main.py`, `requirements.txt`, `Dockerfile`
2. Add dbt models in the appropriate `02_dbt/models/` layers
3. Copy `infra/workflows/example_pipeline.yaml` → `infra/workflows/<source>_pipeline.yaml` and replace `{source}` placeholders
4. Add an entry to `terraform.tfvars` under `sources`
5. Run `terraform plan` then `terraform apply`
6. Open a PR to trigger CI and push Docker images

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full architecture overview, data flow diagram, and service account reference.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT
