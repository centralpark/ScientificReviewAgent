#!/bin/bash

set -euo pipefail

# Deploy the Cloud Run job
gcloud run jobs deploy job-quickstart \
  --source . \
  --tasks 23 \
  --max-retries 3 \
  --region us-west1 \
  --project llm-app-488813

# Execute the deployed job
gcloud run jobs execute job-quickstart --region us-west1 --args="--batch-size","1000"
