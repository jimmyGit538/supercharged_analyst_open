# Supercharged Analyst — Architecture

## Overview

A GCP-native modern data stack for small analytics teams. Extraction, transformation, and analysis are handled by containerised Python jobs, dbt, and BigQuery — orchestrated by Cloud Workflows and scheduled by Cloud Scheduler. Claude Code agents write code, manage PRs, and surface insights automatically.

## Stack

| Layer | Tool |
|---|---|
| Extraction | Python scripts, containerised with Docker |
| Container Registry | GCP Artifact Registry |
| Scheduling | Cloud Scheduler → Cloud Workflows → Cloud Run Jobs |
| Warehouse | BigQuery |
| Transformation | dbt Core |
| Infrastructure | Terraform (GCP provider) |
| Observability | Cloud Logging + Cloud Monitoring |
| Version Control | GitHub |
| CI/CD | GitHub Actions (lint + Docker build/push only) |
| BI | Looker Studio |
| AI | Claude Code + Claude.ai |

## Data Flow

```
External API
    │
    ▼
Cloud Run Job (extraction)
    │  writes to
    ▼
BigQuery: raw dataset
    │
    ├─► Cloud Run Job (dbt-stg-warehouse)  → BigQuery: stg_warehouses
    │
    ├─► Cloud Run Job (dbt-warehouse)      → BigQuery: warehouses
    │
    ├─► Cloud Run Job (dbt-stg-marts)      → BigQuery: stg_marts
    │
    └─► Cloud Run Job (dbt-mart)           → BigQuery: marts
                                                    │
                                                    ▼
                                             Looker Studio
```

Each data source runs its own Cloud Workflow that executes all 5 jobs in sequence. Every workflow is rendered from `infra/terraform/templates/pipeline_workflow.yaml` with the source key and frequency substituted, so a fix to the polling or error handling reaches every source on the next apply. A Cloud Scheduler trigger fires the workflow on the configured cron schedule.

## BigQuery Datasets

| Dataset | Purpose | Written by |
|---|---|---|
| `raw` | Landing zone — extracted data | extraction jobs |
| `stg_warehouses` | Staging views from raw | dbt-stg-warehouse jobs |
| `warehouses` | Cleaned, typed tables | dbt-warehouse jobs |
| `stg_marts` | Staging views for mart layer | dbt-stg-marts jobs |
| `marts` | Fact + dimension tables for BI | dbt-mart jobs |
| `agent_registry` | Append-only agent/skill snapshot log | agent_registry loader |

## Cloud Run Job Naming

Pattern: `{source}-{stage}-{frequency}`

| Stage | dbt layer | What it does |
|---|---|---|
| `extract` | — | Pulls from external API → `raw` |
| `dbt-stg-warehouse` | 1_staging_warehouses | Builds and tests staging views |
| `dbt-warehouse` | 2_warehouses | Seeds + builds and tests warehouse tables |
| `dbt-stg-marts` | 3_staging_marts | Builds and tests mart staging views |
| `dbt-mart` | 4_marts | Builds and tests fact/dimension tables |

Each dbt job runs `dbt build --select <layer>,tag:<source>`. Models are tagged with their source key in `_schema.yml`, so one source's pipeline never rebuilds another's models, and a failing test fails the workflow.

## Service Accounts

Five service accounts, created and managed by Terraform:

| Account | Purpose |
|---|---|
| `extraction-runner` | Runs extraction jobs, writes to `raw` |
| `dbt-runner` | Runs dbt jobs, reads `raw`, writes `warehouses`/`marts` |
| `github-actions-ci` | Pushes Docker images via Workload Identity (no keys) |
| `workflow-runner` | Executes Cloud Workflows, invokes Cloud Run Jobs |
| `scheduler-runner` | Triggers Cloud Workflows on schedule |

## Infrastructure

All GCP resources are managed by Terraform in `infra/terraform/`. The `sources` map in `terraform.tfvars` is the single config point for adding a new data source — Terraform auto-generates all 5 Cloud Run Jobs, a Cloud Workflow, and a Cloud Scheduler trigger per entry.

See `infra/terraform/terraform.tfvars.example` for the configuration format.

## Failure Alerting

`infra/terraform/monitoring.tf` creates one Cloud Monitoring alert policy covering every source
workflow. It fires when an execution finishes with status `FAILED` and emails `alert_email` from
`terraform.tfvars`. Any job in the chain that exits non-zero — an extractor crash, a dbt build
error, or a failing dbt test — makes the workflow raise, so one policy covers all five stages of
every pipeline. It does not cover a workflow that never starts (for example, a Cloud Scheduler
permission error), which only shows in the scheduler's own logs.

## Why GCP-Native Scheduling (not GitHub Actions)

GitHub Actions is CI/CD tooling — it has a 6-hour job timeout, no native GCP service integration, and requires static credentials stored as secrets. Cloud Run Jobs + Cloud Scheduler are purpose-built for containerised, scheduled workloads:

- **Scale to zero** — pay only for execution time
- **Workload Identity** — no static API keys; short-lived tokens issued automatically
- **Structured logging** — every run in Cloud Logging, alertable via Cloud Monitoring
- **Production SLA** — auto-retry, failure notifications, configurable timeouts

## AI Agents

Claude Code agents and skills live in `.claude/`. They accelerate every part of the pipeline:

- `/add-data-source` — full intake: API research → extraction code → dbt models → Terraform config
- `data-extractor` agent — writes Python extraction jobs following project conventions
- `dbt-modeler` agent — writes staging, warehouse, and mart models with tests and docs

Skills are tagged by scope in their `metadata` frontmatter — `universal` for repo-wide workflow,
`layer` for a single layer of the stack, `source` for one external API — and indexed with their
purpose in [`.claude/skills/README.md`](../.claude/skills/README.md).

Agent and skill definitions are version-tracked in BigQuery via `infra/agent_registry/`.
