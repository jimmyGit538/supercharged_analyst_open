# Claude Code Skills

Skills are reference documents that Claude Code loads on demand — either automatically, when the
`description` frontmatter matches what you are doing, or explicitly when you type `/<skill-name>`.
They are how this template teaches Claude its own conventions instead of repeating them in every
prompt.

## Why this folder is flat

Claude Code discovers skills at exactly `.claude/skills/<skill-name>/SKILL.md`. **Category
subfolders are not supported** — moving `pr-workflow/` into `universal/pr-workflow/` would silently
stop it loading, with no error. So grouping here is a documented convention, recorded in each
skill's `metadata` frontmatter and indexed in the tables below, rather than a directory layout.

```yaml
metadata:
  tier: universal | layer | source
  domain: workflow | extraction | modeling | infra
```

`tier` answers *how broadly does this apply?* · `domain` answers *which part of the stack?* and
matches the repo's top-level directories.

## Tier 1 — `universal`

Repo-wide workflow. These apply no matter which pipeline you are touching.

| Skill | Domain | Purpose |
|---|---|---|
| [`setup-fork`](setup-fork/SKILL.md) | workflow | First-run setup for a fresh fork — prerequisites, `.env`, `terraform.tfvars`, GCP infra, CI secrets, and a verified Open-Meteo run. **Start here.** |
| [`add-data-source`](add-data-source/SKILL.md) | workflow | Structured intake for a new API or data source — research, then scaffold extraction, dbt models, and Terraform config. Run before writing any code for a new source. |
| [`pr-workflow`](pr-workflow/SKILL.md) | workflow | Branch naming, commit message format, and PR standards for this repo. |
| [`ci-debugging`](ci-debugging/SKILL.md) | workflow | Diagnosing GitHub Actions failures — sqlfluff, ruff, Docker builds, GCP auth. |
| [`review-pr`](review-pr/SKILL.md) | workflow | Maintainer-side review of an incoming contributor PR (`/review-pr <number>`). |

## Tier 2 — `layer`

Scoped to one layer of the stack. Loaded when you work in that layer's directory or discuss its
concerns.

| Skill | Domain | Covers | Directory |
|---|---|---|---|
| [`python-data-extraction`](python-data-extraction/SKILL.md) | extraction | Extractor structure, credential handling, incremental watermarks, writing to BigQuery. | `01_extraction/` |
| [`data-pipeline-patterns`](data-pipeline-patterns/SKILL.md) | modeling | Choosing a loading strategy — full refresh vs. incremental vs. upsert. | `02_dbt/` |
| [`terraform-gcp-pipeline`](terraform-gcp-pipeline/SKILL.md) | infra | Terraform patterns for Cloud Run Jobs, Scheduler, Workflows, IAM, Secret Manager. | `infra/terraform/` |
| [`pipeline-validation`](pipeline-validation/SKILL.md) | infra | Verifying a deployed pipeline end-to-end — job executions, data landing in BigQuery. | `infra/` |

## Tier 3 — `source`

One external API each. **This is the tier your fork grows.** Adding a data source adds a skill here;
the tiers above stay the same.

| Skill | Domain | API | Reference pipeline |
|---|---|---|---|
| [`api-open-meteo`](api-open-meteo/SKILL.md) | extraction | Open-Meteo — no API key required | `01_extraction/open_meteo/` |
| [`api-fred`](api-fred/SKILL.md) | extraction | FRED (Federal Reserve Economic Data) | `01_extraction/fred_economic/` |
| [`api-coinmarketcap`](api-coinmarketcap/SKILL.md) | extraction | CoinMarketCap | reference only — no extractor in this template |
| [`api-twelvedata`](api-twelvedata/SKILL.md) | extraction | Twelvedata | reference only — no extractor in this template |

## Upstream vs. your fork

The tiers map onto the contribution boundary in [`CONTRIBUTING.md`](../../CONTRIBUTING.md):

- **`universal` + `layer`** — framework. Improvements belong in upstream PRs; every user benefits.
- **`source`** — grows with whatever APIs you extract. A generally useful public API reference is
  welcome upstream; one specific to your own systems stays in your fork.

## Adding a skill

1. Create `.claude/skills/<name>/SKILL.md` — flat, no category folder.
2. Write the `description` so it states both when to auto-invoke **and** when *not* to. This is the
   only thing Claude sees when deciding whether to load the skill, so a vague description means it
   loads at the wrong times or not at all.
3. Set `metadata.tier` and `metadata.domain`.
4. Add a row to the table above.

Keep the frontmatter to the fields allowed by the Agent Skills spec — `name`, `description`,
`license`, `compatibility`, `metadata`, `allowed-tools`. Claude Code tolerates extra keys locally,
but packaging or uploading a skill with an unrecognised key fails hard.

Full contribution guide: [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Related

- **Agents** live in [`../agents/`](../agents). Agents *do* work; skills *inform* it. An agent's
  frontmatter can list the skills it relies on.
- Every change to a skill or agent file is snapshotted to BigQuery by
  [`infra/agent_registry/`](../../infra/agent_registry) as an append-only audit log. Edit the `.md`
  files here — never write to the snapshot tables directly.
