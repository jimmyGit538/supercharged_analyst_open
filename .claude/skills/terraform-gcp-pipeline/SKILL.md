---
name: terraform-gcp-pipeline
description: >
  Terraform patterns and conventions for managing GCP data extraction infrastructure.
  Auto-invoke when writing or modifying Terraform HCL for Cloud Run Jobs, Cloud Scheduler,
  Cloud Workflows, Artifact Registry, Secret Manager, or IAM on GCP. Also invoke when
  adding, removing, or reconfiguring a data source in the extraction pipeline, when
  discussing infrastructure-as-code for the pipeline, or when the user mentions
  "terraform", ".tf files", "tfvars", "infrastructure", or "IaC" in the context of
  the data pipeline. Use alongside the python-data-extraction skill when a task spans
  both application code and infrastructure. Do NOT load for general Terraform questions
  unrelated to this pipeline, or for GCP console/gcloud CLI tasks that don't involve Terraform.
---

# Terraform GCP Pipeline — Standards & Patterns

## 1. Architecture Overview

The pipeline uses per-source Cloud Run Jobs orchestrated by Cloud Workflows, with all infrastructure declared in Terraform. The design principle: adding a new data source should be a single entry in `terraform.tfvars` plus a `terraform apply`.

Key architecture decisions:
- One Docker image per source (independent versioning and dependencies per extractor)
- One Cloud Run Job per source
- One Cloud Scheduler trigger per job
- Cloud Workflows for orchestration and dependency management
- A shared service account with least-privilege IAM
- Artifact Registry as the Docker image store
- Secret Manager for credentials (not env vars)

---

## 2. Project Structure

```
infra/
├── terraform/
│   ├── main.tf               # provider config, GCP API enablement
│   ├── variables.tf          # input variables (project_id, region, sources map)
│   ├── sources.tf            # for_each loop: Cloud Run Jobs + Cloud Schedulers
│   ├── workflows.tf          # Cloud Workflows definition
│   ├── iam.tf                # service accounts and role bindings
│   ├── artifact_registry.tf  # Docker repo
│   ├── secrets.tf            # Secret Manager secret references
│   ├── outputs.tf            # useful outputs (job URIs, scheduler names)
│   ├── terraform.tfvars      # actual values (DO NOT commit secrets)
│   └── .gitignore            # ignore .terraform/, *.tfstate*, terraform.tfvars
```

---

## 3. Provider and API Setup (`main.tf`)

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "workflows.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}
```

---

## 4. Variables (`variables.tf`)

The `sources` map is the single config surface. Each key is a source name; Terraform creates all associated resources from this map.

```hcl
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "sources" {
  description = "Map of data sources to extract. Key = source name."
  type = map(object({
    image_tag   = optional(string, "latest")  # per-source image tag
    schedule    = string                       # cron expression
    memory      = optional(string, "512Mi")
    cpu         = optional(string, "1")
    timeout     = optional(string, "900s")
    max_retries = optional(number, 1)
    env_vars    = optional(map(string), {})    # extra per-source env vars
  }))
}
```

---

## 5. Source Definitions (`terraform.tfvars`)

This is the file to edit when adding, removing, or reconfiguring sources.

```hcl
project_id = "my-gcp-project"
region     = "us-central1"

sources = {
  salesforce = {
    image_tag = "v1.2.0"
    schedule  = "0 */6 * * *"
    memory    = "512Mi"
    timeout   = "1800s"
  }
  stripe = {
    image_tag = "v1.0.3"
    schedule  = "0 * * * *"
    memory    = "256Mi"
  }
  hubspot = {
    image_tag = "v1.1.0"
    schedule  = "0 8 * * *"
    memory    = "512Mi"
    env_vars = {
      HUBSPOT_PORTAL_ID = "12345"
    }
  }
}
```

**Rules:**
- Never commit secrets in `terraform.tfvars` — use Secret Manager references instead
- Always run `terraform plan` before `terraform apply` to review changes
- Use semantic versioning for `image_tag` values, not `latest`, in non-dev environments

---

## 6. IAM (`iam.tf`)

A single shared service account for all extraction jobs with least-privilege roles.

```hcl
resource "google_service_account" "extractor" {
  account_id   = "data-extractor"
  display_name = "Data Extractor Service Account"
}

resource "google_project_iam_member" "scheduler_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.extractor.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.extractor.email}"
}

resource "google_project_iam_member" "workflows_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.extractor.email}"
}
```

---

## 7. Artifact Registry (`artifact_registry.tf`)

```hcl
resource "google_artifact_registry_repository" "extractor" {
  location      = var.region
  repository_id = "data-extractors"
  format        = "DOCKER"
  description   = "Docker images for data extraction jobs"
}
```

Image naming convention: `<region>-docker.pkg.dev/<project>/data-extractors/<source_name>:<tag>`

---

## 8. Cloud Run Jobs + Schedulers (`sources.tf`)

The core `for_each` loop. One Cloud Run Job and one Cloud Scheduler per source, all driven from the `sources` variable.

```hcl
resource "google_cloud_run_v2_job" "extractor" {
  for_each = var.sources
  name     = "extract-${each.key}"
  location = var.region

  template {
    task_count = 1

    template {
      service_account = google_service_account.extractor.email
      timeout         = each.value.timeout
      max_retries     = each.value.max_retries

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/data-extractors/${each.key}:${each.value.image_tag}"

        dynamic "env" {
          for_each = each.value.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }

        resources {
          limits = {
            memory = each.value.memory
            cpu    = each.value.cpu
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_scheduler_job" "extractor_trigger" {
  for_each = var.sources
  name     = "trigger-extract-${each.key}"
  region   = var.region
  schedule = each.value.schedule

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/extract-${each.key}:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.extractor.email
    }
  }

  depends_on = [google_cloud_run_v2_job.extractor]
}
```

---

## 9. Cloud Workflows (`workflows.tf`)

This generates a sequential workflow from the sources map. If the existing Cloud Workflows setup uses parallel steps, error handling, or conditional branches, maintain the workflow YAML as a separate template file and reference it with `templatefile()` instead of generating inline.

```hcl
resource "google_workflows_workflow" "extraction_pipeline" {
  name            = "data-extraction-pipeline"
  region          = var.region
  service_account = google_service_account.extractor.email

  source_contents = yamlencode({
    main = {
      steps = [
        for key, source in var.sources : {
          "extract_${key}" = {
            call = "googleapis.run.v1.namespaces.jobs.run"
            args = {
              name = "namespaces/${var.project_id}/jobs/extract-${key}"
            }
            result = "result_${key}"
          }
        }
      ]
    }
  })

  depends_on = [google_cloud_run_v2_job.extractor]
}
```

To import an existing workflow into Terraform state instead of recreating it:
```bash
terraform import google_workflows_workflow.extraction_pipeline projects/<project>/locations/<region>/workflows/<workflow-name>
```

---

## 10. Outputs (`outputs.tf`)

```hcl
output "job_names" {
  description = "Created Cloud Run Job names"
  value       = { for k, v in google_cloud_run_v2_job.extractor : k => v.name }
}

output "scheduler_names" {
  description = "Created Cloud Scheduler trigger names"
  value       = { for k, v in google_cloud_scheduler_job.extractor_trigger : k => v.name }
}

output "extractor_service_account" {
  description = "Service account email used by extractors"
  value       = google_service_account.extractor.email
}
```

---

## 11. Common Workflows

### Initial Setup
```
1. cd infra/terraform
2. terraform init          # download providers, initialize state
3. terraform plan          # review what will be created
4. terraform apply         # create all resources
5. terraform plan          # should show "No changes" — you're in sync
```

### Adding a New Source
```
1. Create the source's Dockerfile and code in extractors/<source_name>/
2. Build and push the image to Artifact Registry:
   docker build -t <region>-docker.pkg.dev/<project>/data-extractors/<source_name>:v1.0.0 extractors/<source_name>/
   docker push <region>-docker.pkg.dev/<project>/data-extractors/<source_name>:v1.0.0
3. Add entry to sources map in terraform.tfvars
4. terraform plan          # shows new job + scheduler to create
5. terraform apply         # creates them
```

### Removing a Source
```
1. Remove entry from sources map in terraform.tfvars
2. terraform plan          # shows job + scheduler to destroy
3. terraform apply         # removes them cleanly
```

### Updating a Source's Image Version
```
1. Build and push the new image version
2. Update the image_tag value in terraform.tfvars for that source
3. terraform apply         # updates the Cloud Run Job to use the new image
```

---

## 12. Key Decisions and Constraints

- **Per-source Docker images**: Each source has its own image at `data-extractors/<source_name>:<tag>`. Independent versioning enables per-source rollouts and rollbacks.
- **Secrets via Secret Manager**: Credentials belong in Secret Manager, not in env vars or tfvars. The IAM config grants the extractor service account `secretmanager.secretAccessor`.
- **Workflow generation is optional**: The inline `yamlencode` approach works for simple sequential pipelines. For complex orchestration (parallel steps, conditionals, error handlers), use a separate YAML template with `templatefile()`.
- **Local state for now**: Terraform state is local. Before team collaboration or CI/CD, migrate to a GCS backend:
  ```hcl
  terraform {
    backend "gcs" {
      bucket = "my-project-terraform-state"
      prefix = "extraction-pipeline"
    }
  }
  ```

---

## 13. Future Enhancements (Not Yet Implemented)

- Remote state backend (GCS bucket) for team safety and CI/CD
- Watermark persistence (BigQuery table or GCS bucket, provisioned by Terraform, managed by app code)
- CI/CD pipeline (Cloud Build trigger → detect changed sources → build affected images → update image_tag per source in tfvars → terraform apply)
- Monitoring/alerting (Cloud Monitoring alert policies per job, also Terraform-managed)
- Environment separation (dev/staging/prod via Terraform workspaces or separate tfvars files)