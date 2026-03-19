#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="llm-app-488813"
GOOGLE_API_KEY="AIzaSyCE0kuDV_t2ZuASgFqFPaw7MsuZh9E0DMo"
DATA_STORE_ID="aacr-abstracts_1773385412104"
REGION="us-west1"
SERVICE_NAME="scientific-review-agent"
REPOSITORY="agent-deploy"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE_NAME}:${IMAGE_TAG}"

echo "Using project: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "Ensuring APIs are enabled..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

echo "Ensuring Artifact Registry repository exists..."
if ! gcloud artifacts repositories describe "${REPOSITORY}" --location=${REGION} >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location=${REGION} \
    --description="Docker repository for Cloud Run deployments"
fi

echo "Building image: ${IMAGE}"
gcloud builds submit --tag "${IMAGE}" .

echo "Deploying service: ${SERVICE_NAME}"
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "PROJECT_ID=${PROJECT_ID},DATA_STORE_ID=${DATA_STORE_ID},GOOGLE_API_KEY=${GOOGLE_API_KEY}"

echo "Deployment complete."
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format='value(status.url)'
