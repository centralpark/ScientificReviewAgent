# ScientificReviewAgent

LangGraph + Streamlit assistant for reviewing cancer literature from a Vertex AI Search datastore.

## Project Files

- `literature_agent.py`: LangGraph workflow and tool definitions.
- `app.py`: Streamlit chat UI that invokes the compiled graph.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Container image definition for Cloud Run.
- `deploy_cloud_run.sh`: Build and deploy script for Google Cloud Run.
- `.env.example`: Required runtime environment variables.

## Local Run

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file (recommended) or export env vars (see `.env.example`).

Example `.env`:

```bash
PROJECT_ID="your-gcp-project-id"
LOCATION="global"
DATA_STORE_ID="your-discovery-engine-data-store-id"
GOOGLE_API_KEY="your-google-api-key"
```

If you prefer exporting variables:

```bash
export PROJECT_ID="your-gcp-project-id"
export LOCATION="global"
export DATA_STORE_ID="your-discovery-engine-data-store-id"
export GOOGLE_API_KEY="your-google-api-key"
```

4. Start the app:

```bash
streamlit run app.py
```

## Deploy To Google Cloud Run

### Prerequisites

- `gcloud` CLI installed and authenticated.
- Billing-enabled GCP project.
- Enabled APIs:
  - `run.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `artifactregistry.googleapis.com`
  - Discovery Engine APIs used by your datastore.
- Runtime identity has Discovery Engine read permissions for the target data store.

### One-command deploy (from repo root)

```bash
export PROJECT_ID="your-gcp-project-id"
export DATA_STORE_ID="your-discovery-engine-data-store-id"
export GOOGLE_API_KEY="your-google-api-key"
export REGION="us-central1" # optional
export SERVICE_NAME="scientific-review-agent" # optional
./deploy_cloud_run.sh
```

The script builds a container image with Cloud Build, deploys to Cloud Run, and prints the service URL.

## Security Notes

- Do not commit real credentials.
- Prefer using Secret Manager for `GOOGLE_API_KEY` in production.
- `literature_agent.py` now requires `PROJECT_ID`, `DATA_STORE_ID`, and `GOOGLE_API_KEY` at runtime.
