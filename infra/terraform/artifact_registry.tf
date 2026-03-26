resource "google_artifact_registry_repository" "extraction" {
  location      = var.region
  repository_id = "extraction"
  format        = "DOCKER"
  description   = "Extraction job container images"

  depends_on = [google_project_service.apis]
}
