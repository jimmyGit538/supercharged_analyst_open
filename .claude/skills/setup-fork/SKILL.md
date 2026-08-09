---
name: setup-fork
description: >
  End-to-end first-run setup for a fresh fork of this template — prerequisites,
  .env and terraform.tfvars, GCP infrastructure, GitHub Actions secrets and
  variables, image push, and a verified run of the Open-Meteo reference
  pipeline (no API key required). Invoke when the user has just forked or
  cloned the repo and wants to get it running, or says "set up my fork",
  "first-time setup", "get this running", "onboard me". Do NOT invoke for
  adding a new data source (use /add-data-source) or for debugging an
  already-working pipeline.
---

# Fork Setup

Take a fresh fork from clone to rows in `marts`. Most of this is automated; a
few things only the user can do. The pipeline this skill provisions and
verifies by default is **Open-Meteo** — it needs no API key, so there is no
signup step blocking a fresh fork. FRED remains in the repo as an optional
example of a keyed source (see the closing note) but is not part of this
sequence.

## What only the user can do

Never attempt these yourself. Stop, ask, and wait.

| Step | Why |
|---|---|
| Create a GCP project, enable billing | Costs money, tied to their identity |
| `gcloud auth login` and `gcloud auth application-default login` | Interactive browser consent |
| `gh auth login` | Interactive browser consent |
| Approve `terraform apply` | Creates billable resources |

Everything else you run for them.

## Sequence

Work through in order. Report a compact checklist after each phase; do not dump
raw command output unless something fails.

### 1. Prerequisites

```bash
for c in git python3 pip gcloud terraform gh docker; do
  command -v "$c" >/dev/null && echo "  [x] $c" || echo "  [ ] $c  MISSING"
done
gcloud auth list 2>/dev/null | head -3
gh auth status 2>&1 | head -3
```

`docker` is only needed for local image builds — CI builds and pushes on merge,
so a missing docker is a warning, not a blocker. Everything else is required.

If `gcloud` or `gh` is unauthenticated, stop and ask the user to run the login
command. Do not run it yourself — it opens a browser and will hang.

### 2. Local setup

```bash
bash scripts/setup.sh --full-stack
```

Creates `.env` and `infra/terraform/terraform.tfvars` from the examples,
installs dbt and its packages, registers the git hooks, runs `terraform init`.

### 3. Collect the values only the user has

Ask for these together, in one question — not one at a time:

- GCP project ID
- Region (default `us-central1`)

Then fill them in:
- `.env` — `BQ_PROJECT`, `BQ_PROJECT_EXTRACTION`, `BQ_DATASET`
- `infra/terraform/terraform.tfvars` — `project_id`, `region`, `github_repo`

`github_repo` comes from `git remote get-url origin` — derive it, don't ask.

No API key is needed for this sequence — Open-Meteo requires none. If the
user separately asks to enable FRED, see the closing note: that's the one
place a secret (`FRED_API_KEY`) enters the picture, and the same rule applies
there — write it only to `.env` (gitignored) and Secret Manager, never echo
it back.

### 4. Enable APIs

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  workflows.googleapis.com bigquery.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com --project "$PROJECT_ID"
```

`secretmanager.googleapis.com` is enabled here even though the default
`open-meteo` source needs no secret — `infra/terraform/secrets.tf` and the
optional FRED example both depend on the API being on.

### 5. Provision infrastructure

```bash
cd infra/terraform && terraform plan
```

Show the user a summary of what will be created and **wait for approval** before
`terraform apply`. This is the billable step.

### 6. Dataset ACLs

```bash
export PROJECT_ID=... REGION=... GITHUB_REPO=...
bash infra/setup.sh
```

Terraform creates the datasets but cannot manage dataset-level access. Skipping
this is the classic silent failure: everything deploys, then jobs 403 at runtime.

### 7. GitHub Actions configuration

```bash
bash scripts/setup.sh --configure-github
```

Reads the terraform outputs and sets `WORKLOAD_IDENTITY_PROVIDER` and
`SERVICE_ACCOUNT` (secrets) plus `GCP_PROJECT_ID` and `GCP_REGION` (variables).
Requires `gh` authenticated with admin on the fork.

### 8. Push images

Images reach Artifact Registry when the Deploy workflow runs on `main`. If the
fork's `main` is already current, trigger it directly:

```bash
gh workflow run deploy.yml && sleep 20 && gh run list --workflow=deploy.yml --limit 1
```

If it reports success but skipped the push, step 7 did not take — check
`gh secret list` and `gh variable list`.

### 9. Run and verify

```bash
gcloud workflows run open-meteo-pipeline --location="$REGION"
```

Then confirm data actually landed — a green workflow is not proof:

```bash
bq query --use_legacy_sql=false --maximum_bytes_billed=1000000000 \
  'SELECT COUNT(*) AS rows, COUNT(DISTINCT location_id) AS locations, MAX(date) AS latest
   FROM `'"$PROJECT_ID"'.raw.open_meteo_daily_weather`'

bq query --use_legacy_sql=false --maximum_bytes_billed=1000000000 \
  'SELECT COUNT(*) AS rows, MAX(date) AS latest
   FROM `'"$PROJECT_ID"'.marts.fct_open_meteo_daily_weather`'
```

Expect ~20 distinct locations in `raw` (the fixed city list in
`01_extraction/open_meteo/main.py::LOCATIONS`). Fewer means some requests
failed — check the extraction job log:

```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=open-meteo-extract-daily' \
  --limit=20 --project "$PROJECT_ID"
```

## Finishing

Report a single checklist: what is done, what the user still owes, and the one
next command. If anything failed, say so plainly with the error — never report
a phase as complete because the command exited 0 when the data says otherwise.

## Optional: enabling FRED afterward

FRED ships in the repo (commented out in `terraform.tfvars.example`) as a
working example of a source that needs a Secret-Manager-backed API key — the
pattern to copy when wiring up your own keyed source via `/add-data-source`.
It is not part of this setup sequence. If the user asks for it separately:

1. Get a free key: https://fredaccount.stlouisfed.org/apikeys (their step, not yours)
2. `gcloud secrets create FRED_API_KEY ...` and add the version (same pattern
   as step 4 used to, before Open-Meteo replaced it as the default) — it must
   exist before `terraform apply`, since `secrets.tf` reads it as a `data` source
3. Uncomment the `fred-economic` block in `terraform.tfvars`, `terraform plan`, `terraform apply`
4. `gcloud workflows run fred-economic-pipeline --location="$REGION"`, then verify
   `raw.fred_economic_observations` and `marts.fct_fred_economic_indicators` the
   same way step 9 verifies Open-Meteo
