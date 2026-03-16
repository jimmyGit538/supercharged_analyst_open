#!/usr/bin/env bash
# GCP project bootstrap script
# Run once to configure the project environment.
# Replace all YOUR_* placeholders before executing.

set -euo pipefail

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="YOUR_REGION"          # e.g. us-central1
REPO_NAME="extraction"

echo "Configuring project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Extraction job container images"

# Create extraction service account
gcloud iam service-accounts create extraction-runner \
  --display-name="Extraction Job Runner"

SA_EMAIL="extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant BigQuery Data Editor on raw dataset only (least privilege)
bq add-iam-policy-binding \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataEditor" \
  "${PROJECT_ID}:raw"

# Allow Cloud Run to use this service account
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser"

echo "Bootstrap complete. Next: create a Cloud Run Job per extraction source."
