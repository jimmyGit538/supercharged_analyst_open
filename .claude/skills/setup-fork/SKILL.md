---
name: setup-fork
description: >
  End-to-end first-run setup for a fresh fork of this template — prerequisites,
  .env and terraform.tfvars, GCP infrastructure, GitHub Actions secrets and
  variables, image push, and a verified run of the FRED reference pipeline.
  Invoke when the user has just forked or cloned the repo and wants to get it
  running, or says "set up my fork", "first-time setup", "get this running",
  "onboard me". Do NOT invoke for adding a new data source (use
  /add-data-source) or for debugging an already-working pipeline.
---

# Fork Setup

Take a fresh fork from clone to rows in `marts`. Most of this is automated; a
few things only the user can do.

## What only the user can do

Never attempt these yourself. Stop, ask, and wait.

| Step | Why |
|---|---|
| Create a GCP project, enable billing | Costs money, tied to their identity |
| `gcloud auth login` and `gcloud auth application-default login` | Interactive browser consent |
| `gh auth login` | Interactive browser consent |
| Get a FRED API key | Third-party signup: https://fredaccount.stlouisfed.org/apikeys |
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
- FRED API key

Then fill them in:
- `.env` — `BQ_PROJECT`, `BQ_PROJECT_EXTRACTION`, `BQ_DATASET`, `FRED_API_KEY`
- `infra/terraform/terraform.tfvars` — `project_id`, `region`, `github_repo`

`github_repo` comes from `git remote get-url origin` — derive it, don't ask.

Never write the FRED key anywhere except `.env` (gitignored) and Secret Manager.
Never echo it back.

### 4. Enable APIs and create the secret

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  workflows.googleapis.com bigquery.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com --project "$PROJECT_ID"

gcloud secrets create FRED_API_KEY --replication-policy=automatic --project "$PROJECT_ID"
printf '%s' "$FRED_API_KEY" | gcloud secrets versions add FRED_API_KEY --data-file=- --project "$PROJECT_ID"
```

The secret name must be exactly `FRED_API_KEY` — `infra/terraform/sources.tf`
mounts secrets by matching the secret name to the env var name. It must exist
*before* apply: `secrets.tf` reads it as a `data` source, so the plan fails
without it.

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
gcloud workflows run fred-economic-pipeline --location="$REGION"
```

Then confirm data actually landed — a green workflow is not proof:

```bash
bq query --use_legacy_sql=false --maximum_bytes_billed=1000000000 \
  'SELECT COUNT(*) AS rows, COUNT(DISTINCT series_id) AS series, MAX(date) AS latest
   FROM `'"$PROJECT_ID"'.raw.fred_economic_observations`'

bq query --use_legacy_sql=false --maximum_bytes_billed=1000000000 \
  'SELECT COUNT(*) AS rows, MAX(date) AS latest
   FROM `'"$PROJECT_ID"'.marts.fct_fred_economic_indicators`'
```

Expect ~118 distinct series in `raw`. Fewer means some series ids were rejected —
that is logged, not fatal. Check the extraction job log:

```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=fred-economic-extract-daily AND textPayload:REJECTED' \
  --limit=20 --project "$PROJECT_ID"
```

The state-level series id patterns (`ATNHPIUS<FIPS>000A`,
`ENUC<FIPS>40010SA`) are the least-verified part of the reference source. If
they are rejected, correct the lists in `01_extraction/fred_economic/main.py`.

## Finishing

Report a single checklist: what is done, what the user still owes, and the one
next command. If anything failed, say so plainly with the error — never report
a phase as complete because the command exited 0 when the data says otherwise.
