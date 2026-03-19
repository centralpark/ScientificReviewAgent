#!/bin/bash

set -euo pipefail

JOB_NAME="wrap-to-vertex-jsonl"

# Deploy the Cloud Run job
gcloud run jobs deploy "$JOB_NAME" \
  --source . \
  --tasks 1 \
  --max-retries 2 \
  --memory 16Gi \
  --cpu 4 \
  --region us-west1 \
  --task-timeout=1h \
  --project llm-app-488813

# Execute the deployed job
gcloud run jobs execute "$JOB_NAME" \
  --region us-west1 \
  --update-env-vars="INPUT_GCS_PATH=gs://aacr-abstracts-data-lake/aacr_final_results.jsonl,OUTPUT_GCS_PATH=gs://aacr-abstracts-data-lake/aacr_final_results_google.jsonl"
