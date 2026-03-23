

**Modern Data Stack**

Strategy & Implementation Plan

**GCP-Native Edition**

————————————————————

*Cloud Run · Cloud Scheduler · BigQuery · dbt · Claude*


# **Executive Summary**

This document outlines a cost-effective, AI-powered modern data stack designed for small analytics teams with Google Cloud Platform experience. The strategy is built entirely within the GCP ecosystem — using Cloud Run Jobs, Cloud Scheduler, and BigQuery as the operational backbone — to maximise reliability, security, and observability from day one, without the compromises that come with simpler scheduling alternatives.

| Goal: Enable a small team to extract, store, transform, and analyse data with minimal engineering overhead, powered by AI agents that write code, manage repositories, and surface insights automatically — all within a fully managed, production-grade GCP environment. |
| :---- |

## **Guiding Principles**

* **GCP-native:** All scheduling, execution, and storage runs within a single GCP project

* **Production-first:** Production-grade infrastructure from week one, not retrofitted later

* **Secure by default:** Native IAM and Workload Identity — no credentials floating in environment variables

* **AI-empowered:** Any analyst can drive engineering work through Claude without writing code

* **Auditable:** Every change tracked in Git with AI-written, human-reviewed PRs

# **Why GCP-Native Scheduling Over GitHub Actions**

GitHub Actions is the most common recommendation for teams new to cloud infrastructure — it requires no Docker knowledge, no IAM configuration, and can be set up with a single YAML file in under ten minutes. For a team with GCP Cloud Run experience, however, it represents a meaningful set of tradeoffs that compound over time.

## **The Case Against GitHub Actions for Data Pipelines**

* GitHub Actions was designed for CI/CD — building and deploying code. Using it as a data pipeline scheduler means running workloads on ephemeral GitHub-hosted VMs with a 6-hour job timeout, no persistent compute context, and limited native integration with GCP services.

* Credentials must be stored as GitHub Secrets and injected as environment variables, increasing the attack surface compared to GCP Workload Identity Federation, which issues short-lived tokens automatically with no static keys.

* Observability is limited to the GitHub Actions UI and email alerts on failure. There is no native integration with Cloud Monitoring, no structured logs, no custom alert policies, and no dashboarding.

* The free tier of 2,000 minutes/month sounds generous but disappears quickly once multiple sources are running on frequent schedules. At scale, costs become less predictable than Cloud Run’s per-execution billing.

## **The Case For Cloud Run Jobs \+ Cloud Scheduler**

| GCP Advantage: Cloud Run Jobs and Cloud Scheduler are purpose-built for exactly this workload: containerised, scheduled, short-lived execution with full GCP service integration. |
| :---- |

* Each extraction script runs as an isolated Docker container. Dependencies are pinned, environments are reproducible, and there is no “works on my machine” problem.

* Cloud Scheduler triggers jobs on any cron expression. Retries, dead-letter handling, and failure notifications are configurable natively — no custom error-handling code required.

* Cloud Run Jobs scale to zero. There is no idle compute cost — you pay only for the CPU and memory consumed during actual execution, which for typical extraction jobs amounts to pennies per run.

* Workload Identity allows Cloud Run Jobs to authenticate to BigQuery using a service account without any exported keys. Permissions are managed in IAM, audited automatically, and rotated without code changes.

* Every run produces structured logs in Cloud Logging. Dashboards, alert policies, and uptime checks can be built in Cloud Monitoring. When a job fails at 3am, your team gets a PagerDuty or Slack alert, not an email buried in a GitHub notifications inbox.

* The entire setup — Artifact Registry, Cloud Run Job definitions, Cloud Scheduler configs — is codified in Terraform or gcloud CLI commands, making the infrastructure as auditable and version-controlled as the application code itself.

## **Side-by-Side Comparison**

|  | GCP Cloud Run \+ Scheduler | GitHub Actions |
| ----- | ----- | ----- |
| **Infrastructure** | Fully GCP-managed containers Scales to zero, no idle cost | Runs on GitHub-hosted VMs No infrastructure to manage |
| **Reliability** | Production-grade SLA Auto-retry, dead-letter queues | Best-effort; 6hr job timeout Occasional queue delays |
| **Observability** | Cloud Logging \+ Monitoring Alerts, dashboards, trace IDs | Job logs in GitHub UI Email alerts on failure only |
| **Security / IAM** | Workload Identity \+ service accounts No secrets in env vars or YAML | GitHub Secrets for credentials Slightly higher exposure surface |
| **GCP Integration** | Native IAM to BigQuery No API key management | Requires exported service account key stored as secret |
| **Cost** | Pennies per run Pay only for execution time | 2,000 free mins/month Free at small scale |
| **Setup Time** | 30–60 min (Docker \+ Scheduler) | \~10 min (YAML file in repo) |
| **Best For** | ✓ Production from day one Teams with GCP experience | Rapid prototyping Teams new to cloud infra |

| Bottom line: GitHub Actions is easier to start with. Cloud Run is the right answer for anyone who has used it before and cares about reliability, security, and observability. The 30–60 minute upfront investment in containerisation pays dividends from the first time a job fails at an inconvenient hour and your team already has structured logs, automatic retries, and a Slack alert waiting for them. |
| :---- |

# **Stack Architecture**

The stack is composed of six functional layers, all anchored in GCP. Each layer is purpose-built for its role, integrates natively with adjacent layers, and requires minimal operational management.

## **Data Flow**

| ①  Extract: Python scripts pull data from source systems (APIs, databases, SaaS tools). Each script is packaged as a Docker container and stored in GCP Artifact Registry. |
| :---- |

| ②  Schedule \+ Execute: Cloud Scheduler triggers Cloud Run Jobs on a defined cron schedule. Each job runs the container, executes the extraction script, and terminates. Logs stream to Cloud Logging automatically. |
| :---- |

| ③  Load: Scripts write directly to BigQuery using the google-cloud-bigquery Python library, authenticated via Workload Identity. Raw data lands in a dedicated raw dataset. |
| :---- |

| ④  Transform: dbt Core runs SQL transformations inside BigQuery, building clean staging and mart models from raw tables. dbt can be triggered manually, via Cloud Scheduler, or on GitHub PR merge. |
| :---- |

| ⑤  Serve: Looker Studio connects natively to BigQuery production mart models. Analysts get a free self-serve dashboard layer with zero additional infrastructure. |
| :---- |

| ⑥  AI Layer: Claude Code acts as a resident senior engineer — writing scripts, Dockerfiles, dbt models, and PRs. Claude.ai empowers analysts to describe needs in plain English and drive the full pipeline. |
| :---- |

# **Tool-by-Tool Breakdown**

## **1\.  Python Scripts (Containerised)**

Each data source gets its own Python extraction script. Scripts are written and maintained by Claude Code, stored in GitHub, and containerised using Docker. Each container is pushed to GCP Artifact Registry, giving Cloud Run a versioned, immutable image to execute on schedule.

* One script per data source — isolated, testable, independently deployable

* Docker ensures consistent execution regardless of environment

* Artifact Registry stores versioned images — rollback is a single command

* Claude Code writes the Dockerfile alongside the extraction script

### **Example Container Structure**

| extraction-job/ ├── main.py              \# extraction logic ├── requirements.txt    \# pinned dependencies └── Dockerfile \# Dockerfile (Claude Code writes this) FROM python:3.11-slim WORKDIR /app COPY requirements.txt . RUN pip install \-r requirements.txt COPY main.py . CMD \["python", "main.py"\] |
| :---- |

## **2\.  Cloud Run Jobs**

Cloud Run Jobs are GCP’s purpose-built primitive for running containerised batch workloads. A Job defines the container to run, the service account to use, resource limits, retry policy, and parallelism. It does not run continuously — it executes on demand or on a schedule and terminates when complete.

| Key benefit: Cloud Run Jobs are serverless. There is zero idle cost. A job that runs for 45 seconds and uses 512MB of memory costs approximately $0.002 per execution. |
| :---- |

* One Cloud Run Job per extraction script — independent schedules and failure isolation

* Configurable retry count and backoff — transient API failures are handled automatically

* Resource limits (CPU, memory) are set per job — runaway jobs cannot consume unbounded resources

* Execution history and logs are retained in Cloud Logging for audit and debugging

## **3\.  Cloud Scheduler**

Cloud Scheduler is GCP’s managed cron service. It triggers Cloud Run Jobs on any cron expression and requires no server, no daemon, and no uptime management. The first three jobs per month are free; additional jobs are $0.10/month each.

* Configured via gcloud CLI or Terraform — infrastructure as code from day one

* Timezone-aware scheduling — no UTC conversion errors

* Automatic retry on missed executions if the scheduler itself experiences downtime

* Integrates with Cloud Monitoring for alerting on missed or failed trigger attempts

## **4\.  Cloud Logging \+ Monitoring**

Every Cloud Run Job execution automatically emits structured logs to Cloud Logging. This gives the team a queryable, searchable, permanent record of every pipeline run without any additional instrumentation code.

* Log-based alerts: trigger a Slack or PagerDuty notification when a job fails or produces an error log

* Cloud Monitoring dashboards: visualise job success rates, execution duration, and error frequency

* Error Reporting: automatically groups and surfaces repeated exceptions across job runs

* All of this is available within the same GCP project at no additional tooling cost

## **5\.  GitHub \+ Claude Code**

All application code — extraction scripts, Dockerfiles, dbt models, and infrastructure configuration — lives in a single GitHub repository. Claude Code operates directly on this repository, writing code, opening pull requests, and maintaining the codebase autonomously on request.

* Write Python extraction scripts from a plain-English description of the data source

* Write and maintain Dockerfiles for each extraction job

* Write dbt staging models, mart models, tests, and column-level documentation

* Review existing code for bugs, performance issues, or security problems

* Open pull requests with clear descriptions for team review before any merge

* Diagnose failed Cloud Run Jobs from structured log output and propose fixes

GitHub Actions is still used in this stack — but only for CI/CD (linting, testing on PR, building and pushing Docker images to Artifact Registry). It is not used as a data pipeline scheduler.

## **6\.  BigQuery**

Google BigQuery is the warehouse. Python scripts load raw data directly using the google-cloud-bigquery library, authenticated via the Cloud Run Job’s Workload Identity service account. No API keys, no credential files, no manual rotation.

| IAM advantage: The Cloud Run Job’s service account is granted only the BigQuery Data Editor role on the raw dataset. Least-privilege access is enforced at the infrastructure level, not in application code. |
| :---- |

* 10 GB storage free \+ 1 TB queries/month free — covers most small teams entirely

* Serverless — zero infrastructure management, no clusters to provision

* Native Looker Studio integration — no additional BI connectors or licensing

* dbt \+ BigQuery is one of the most widely documented pairings in the modern data stack ecosystem

## **7\.  dbt Core**

dbt Core handles all transformations inside BigQuery. Raw tables loaded by extraction jobs are cleaned, renamed, typed, and joined into analyst-ready staging and mart models. dbt runs entirely within BigQuery — it never moves data externally.

### **Repository Structure**

| your-data-repo/ ├── extraction/ │   ├── salesforce/ │   │   ├── main.py │   │   ├── requirements.txt │   │   └── Dockerfile │   └── google\_ads/ │       ├── main.py │       └── Dockerfile ├── dbt/ │   ├── models/ │   │   ├── staging/ │   │   │   ├── stg\_salesforce\_\_opportunities.sql │   │   │   └── stg\_google\_ads\_\_campaigns.sql │   │   └── marts/ │   │       ├── fct\_revenue.sql │   │       └── dim\_customers.sql │   ├── tests/ │   └── dbt\_project.yml ├── infra/                  \# gcloud / Terraform configs └── .github/workflows/      \# CI only: lint, test, docker build+push |
| :---- |

dbt docs generate creates a full documentation website hosted for free on GitHub Pages, giving analysts a searchable model catalogue, column descriptions written by Claude Code, and a visual lineage graph showing the complete transformation chain from raw source to production table.

## **8\.  Looker Studio \+ Claude.ai**

Looker Studio connects natively to BigQuery mart models at no cost, giving analysts a self-serve dashboard layer. Claude.ai empowers analysts to request new data, write SQL, understand unfamiliar tables, and QA outputs — all in plain English. The two tools together mean analysts rarely need to wait for engineering to get answers.

# **Warehouse Comparison**

BigQuery is the natural and strongly recommended warehouse for this stack given the full GCP commitment. The comparison below is provided for reference when evaluating future options.

| Warehouse | Pricing Model | Best For | Complexity |
| ----- | ----- | ----- | ----- |
| **BigQuery** **(Recommended)** | Pay-per-query $6.25/TB \+ free tier | SQL analytics, GCP teams, small–mid teams | Low |
| **Snowflake** | Credit-based compute \~$2/credit, no free tier | Data sharing, multi-cloud, larger eng teams | Medium |
| **Databricks** | DBU-based Compute \+ cloud costs | ML/AI workloads, Spark pipelines, data science | High |

* Migrate to Snowflake if cross-cloud data sharing with external partners becomes a priority.

* Evaluate Databricks only when the team begins serious ML model training on warehouse data at significant scale.

# **Implementation Plan**

The stack can be fully operational within four to six weeks. Phase 1 is the most involved due to GCP environment setup and containerisation, but this investment is made once and pays forward across every subsequent extraction job added to the system.

| Phase | Timeline | Actions | Outcome |
| ----- | ----- | ----- | ----- |
| **Phase 1** **Foundation** | Week 1–2 | Set up GCP project \+ IAM service accounts Enable BigQuery, Cloud Run, Cloud Scheduler APIs Write first Python extraction script Containerise with Docker \+ push to Artifact Registry | GCP environment ready First container running |
| **Phase 2** **Scheduling** | Week 2–3 | Configure Cloud Run Job per data source Set up Cloud Scheduler triggers Enable Cloud Logging alerts on job failure Validate data landing in BigQuery raw layer | Reliable automated pipeline live |
| **Phase 3** **AI Layer** | Week 2–3 | Install Claude Code Set up Claude.ai for analysts Claude Code writes \+ reviews scripts and Dockerfiles Establish GitHub PR review workflow | AI-assisted dev pipeline active |
| **Phase 4** **Transform** | Week 3–5 | Install dbt Core Claude Code writes staging \+ mart models Add dbt tests and schema documentation Host dbt docs on GitHub Pages | Clean trusted data in BigQuery |
| **Phase 5** **Analytics** | Week 4–6 | Connect Looker Studio to BigQuery mart models Build analyst dashboards Onboard analysts to Claude.ai workflow Document request → implement → review process | Analysts fully self-serve |

# **Full Stack Summary**

| Layer | Tool | Cost | Complexity |
| ----- | ----- | ----- | ----- |
| Extraction | Python Scripts | Free | Low |
| Containerisation | Docker \+ Artifact Registry | \~$0–1/mo storage | Low–Medium |
| Scheduling | Cloud Scheduler | Free (3 jobs free/mo) | Low |
| Orchestration | Cloud Run Jobs | Pay-per-execution (\~pennies) | Low–Medium |
| Observability | Cloud Logging \+ Monitoring | Free tier generous | Low |
| Version Control | GitHub | Free | Very Low |
| AI Agent | Claude Code | \~$20–$100/mo | Low |
| Warehouse | BigQuery | Free tier → pay-per-query | Low |
| Transformation | dbt Core | Free | Medium |
| Docs Hosting | GitHub Pages | Free | Very Low |
| BI / Dashboards | Looker Studio | Free | Very Low |
| Analyst AI | Claude.ai | $20/user/mo | Very Low |

| Total monthly cost (small team): Approximately $40–$120/month for a team of 2–3 analysts. Cloud Run and Cloud Scheduler costs are negligible at small scale (typically under $5/month combined). The primary recurring costs are Claude Code API usage (\~$20–$100) and Claude.ai seats ($20/user/month). |
| :---- |

# **Risks & Considerations**

* **Query costs:** BigQuery query costs can spike if analysts run poorly scoped queries against large tables. Use column pruning, table partitioning, and query cost controls (maximum bytes billed) from day one. dbt can enforce partition filters in model definitions.

* **Container overhead:** Docker adds a layer of abstraction that teams unfamiliar with containers may find challenging to debug initially. Claude Code mitigates this by writing and maintaining Dockerfiles, and the consistency benefits outweigh the learning curve for anyone with existing Cloud Run experience.

* **AI code review:** All pull requests generated by Claude Code should be reviewed by a human before merging. The GitHub PR workflow is the human-in-the-loop checkpoint that keeps the team in control of what runs in production.

* **Pipeline dependencies:** As the number of extraction jobs grows, consider adding a lightweight orchestrator like Cloud Workflows or Prefect Cloud to manage dependencies between jobs (e.g., ensuring dbt only runs after all extraction jobs have completed successfully).

# **Recommended Next Steps**

* Create a GCP project and enable the BigQuery, Cloud Run, Cloud Scheduler, and Artifact Registry APIs

* Create a GitHub repository and initialise the folder structure shown above

* Create a service account with BigQuery Data Editor permissions on the raw dataset

* Write the first Python extraction script for the highest-priority data source

* Containerise the script with Docker and push the image to Artifact Registry

* Create a Cloud Run Job pointing to the container and verify it executes successfully

* Configure a Cloud Scheduler trigger on the desired cron schedule

* Set up a Cloud Logging alert to notify on job failure

* Install Claude Code and use it to write the second extraction script end-to-end

* Initialise dbt Core and ask Claude Code to write the first staging model

* Connect Looker Studio to BigQuery and build a first dashboard on clean mart data

—

*GitHub Actions is easier to start with. Cloud Run is the right answer for anyone who cares about reliability, security, and observability from day one. For a team that already knows GCP, the 30–60 minute upfront investment in containerisation is the single best infrastructure decision you can make — and with Claude Code writing the Dockerfiles, it barely registers as work at all.*
