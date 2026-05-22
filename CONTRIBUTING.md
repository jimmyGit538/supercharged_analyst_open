# Contributing

## Adding a data source

Use the Claude Code skill — it handles everything:

```
/add-data-source
```

If you prefer to do it manually, follow the steps in the [README](README.md#adding-more-data-sources).

## PR conventions

- All changes go through a GitHub PR — no direct pushes to `main`
- CI must pass (Python lint, SQL lint, Docker build)
- One logical change per PR; keep diffs reviewable
- PR titles: `add <source> pipeline`, `fix <source> extraction`, `refactor dbt <model>`

## Coding conventions

**Extraction jobs (`01_extraction/`)**
- One directory per source: `main.py`, `requirements.txt`, `Dockerfile`
- Use `google.cloud.bigquery` for all BigQuery writes
- Read secrets from environment variables (injected by Cloud Run from Secret Manager)
- Add `maximum_bytes_billed` to all BigQuery queries

**dbt models (`02_dbt/models/`)**
- Follow the 4-layer naming: `stg_<source>__<entity>`, `wh_<source>_<entity>`, `fct_<name>`, `dim_<name>`
- Every model must have column-level documentation and dbt tests
- All SQL must pass `sqlfluff lint` with the BigQuery dialect

**Terraform (`infra/terraform/`)**
- All infrastructure changes go through `terraform plan` → review → `terraform apply`
- No manual GCP console changes
- `terraform.tfvars` is gitignored — never commit it

## How Claude Code agents work in this repo

Agent definitions live in `.claude/agents/` and skill definitions in `.claude/skills/`. These are loaded automatically by Claude Code when you open the repo.

- **`data-extractor` agent** — writes Python extraction code following project conventions
- **`dbt-modeler` agent** — writes dbt models with tests and column docs
- **`/add-data-source` skill** — full intake and scaffolding for a new pipeline

Edits to agent/skill `.md` files are auto-snapshotted to the `agent_registry` BigQuery dataset the next time they are loaded.

## Agent Registry

To manually sync all definitions to BigQuery:

```bash
cd infra/agent_registry
python manage.py sync
```

To see the snapshot history for an agent:

```bash
python manage.py list --name data-extractor --table agent_snapshots
```
