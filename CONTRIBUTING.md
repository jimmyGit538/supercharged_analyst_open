# Contributing

## What belongs here vs your fork

This repo is a template. Your own data sources — extraction jobs in `01_extraction/`, dbt models, and `terraform.tfvars` — belong in your fork, not in upstream PRs.

Upstream contributions are things that benefit every user of the template:

- New skills (API references, reusable patterns)
- Alternative infrastructure (e.g. AWS equivalents to the GCP Terraform modules)
- Improvements to existing skills or agents
- Bug fixes in shared tooling (agent registry, pre-commit hooks, CI)

## Adding a new skill

Skills are Claude Code reference documents that auto-load when relevant. A good candidate is a public API reference or a reusable data pipeline pattern that many users of this template would need.

**File location:** `.claude/skills/<name>/SKILL.md`

**Format:** YAML frontmatter followed by markdown documentation.

```yaml
---
name: my-api
description: >
  My API reference. Auto-invoke when writing code that calls the My API,
  building My API extractors, or answering questions about My API endpoints,
  parameters, or response shapes. Do NOT load for general discussions
  unrelated to the My API.
---
```

Follow the body with endpoint documentation, common parameters, response shapes, and annotated code examples. Look at the existing skills for reference:

- `.claude/skills/fred-api/SKILL.md` — FRED economic data API
- `.claude/skills/coinmarketcap-api/SKILL.md` — CoinMarketCap API
- `.claude/skills/terraform-gcp-pipeline/SKILL.md` — GCP Terraform patterns

PR title convention: `add <name> skill`

## Adding alternative infrastructure

The existing Terraform modules under `infra/terraform/` are GCP-native. If you want to contribute an equivalent for another cloud provider (e.g. AWS, Azure), place it under `infra/` alongside the existing directory:

```
infra/
  terraform/        # GCP (existing)
  aws/              # AWS (example)
```

Your infrastructure contribution must:

- Cover the same pipeline stages: `extract`, `dbt-stg-warehouse`, `dbt-warehouse`, `dbt-stg-marts`, `dbt-mart`
- Include a `README.md` in the new directory explaining how to deploy it
- Follow the same service account / IAM principle of least privilege pattern
- Never include real credentials or project identifiers — use placeholder values

PR title convention: `add <provider> infrastructure`

## Improving existing skills or agents

Edit `.claude/skills/<name>/SKILL.md` or `.claude/agents/<name>.md` directly. Changes are auto-snapshotted to the agent registry BigQuery table the next time they are loaded — no manual sync step needed.

PR title conventions:
- `improve <name> skill`
- `improve <name> agent`

## PR conventions

- All changes go through a GitHub PR — no direct pushes to `main`
- CI must pass (Python lint, SQL lint, Docker build)
- One logical change per PR; keep diffs reviewable

## Agent Registry

To manually sync all agent and skill definitions to BigQuery:

```bash
cd infra/agent_registry
python manage.py sync
```

To see the snapshot history for an agent:

```bash
python manage.py list --name data-extractor --table agent_snapshots
```
