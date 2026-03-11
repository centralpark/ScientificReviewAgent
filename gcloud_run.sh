#!/bin/bash

set -euo pipefail

# Deploy the Cloud Run job
gcloud run jobs deploy job-quickstart \
  --source . \
  --command="python" \
  --args="process_aacr_dois.py","--batch-size","500","--save-frequency","1000","--failed-dois-json","gs://aacr-abstracts-data-lake/failed_dois_1773156557.json" \
  --tasks 1 \
  --max-retries 1 \
  --memory 4Gi \
  --region us-west1 \
  --task-timeout=6h \
  --project llm-app-488813

# Execute the deployed job
gcloud run jobs execute job-quickstart --region us-west1
