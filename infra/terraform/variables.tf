variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "github_repo" {
  description = "GitHub repository in org/repo format (lowercase)"
  type        = string
}

variable "sources" {
  description = <<-EOT
    Map of data source pipelines. Each key is a source name (e.g. "indices").
    Terraform auto-generates 5 Cloud Run Jobs per source:
      1 extraction job + 4 dbt jobs (stg-warehouse, warehouse, stg-marts, mart).
  EOT
  type = map(object({
    extraction_image = string                    # Image name in Artifact Registry (e.g. "twelvedata-indices")
    frequency        = string                    # Run cadence: daily, hourly, etc.
    schedule         = string                    # Cron expression for Cloud Scheduler
    schedule_tz      = optional(string, "UTC")   # Scheduler timezone
    env_vars         = optional(map(string), {}) # Extra env vars for the extraction job
    secrets          = optional(map(string), {}) # Secret name → version (e.g. "TWELVEDATA_API_KEY" = "latest")
    timeout          = optional(string, "600s")  # Cloud Run Job timeout (default 10 min; use "3600s" for long extractors)
  }))
}
