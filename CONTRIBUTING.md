# Contributing

## Initial setup

After cloning, run the setup script once:

```bash
bash scripts/setup.sh
```

This registers the `merge=ours` driver and installs a pre-push hook that hard-blocks any accidental push of private pipeline code to this repo.

### Recommended remote configuration

This template is designed for a three-remote workflow:

| Remote | Points to | Purpose |
|--------|-----------|---------|
| `upstream` | `github.com/jimmyGit538/supercharged_analyst_open` | Canonical public template — fetch framework updates from here |
| `origin` | Your GitHub fork of `supercharged_analyst_open` | Push PR branches here |
| `private` | Your private pipelines repo | Your own extraction jobs, dbt models, credentials |

**First-time setup after forking:**

```bash
# Clone your fork
git clone https://github.com/<you>/supercharged_analyst_open.git
cd supercharged_analyst_open

# Add the canonical public repo as upstream
git remote add upstream https://github.com/jimmyGit538/supercharged_analyst_open.git

# Add your private repo
git remote add private https://github.com/<you>/supercharged_analyst_private.git

# Run one-time setup
bash scripts/setup.sh
```

### Contributing a change back to the public repo

Never push branches that contain private pipeline commits. Instead, cherry-pick only the public changes onto a clean branch:

```bash
# Start from the latest public template
git fetch upstream
git checkout -b my-contribution upstream/main

# Cherry-pick only the commits you want to share
git cherry-pick <sha>

# Push to your fork and open a PR against upstream/main
git push origin my-contribution
```

If you try to push a branch that touches `01_extraction/`, `02_dbt/`, or `infra/workflows/`, the pre-push hook will block it and tell you which commits are the problem.

### Pulling framework updates into your private repo

```bash
git fetch upstream
git merge upstream/main
# The merge=ours driver keeps your private paths (01_extraction/, 02_dbt/, etc.) intact
```

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
