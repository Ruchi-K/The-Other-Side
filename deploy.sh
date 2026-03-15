#!/bin/bash
# deploy.sh — Build, push, and deploy The Other Side to Cloud Run
# Usage: bash deploy.sh

set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_NAME="the-other-side"
BUCKET_NAME="${PROJECT_ID}-tos-videos"
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/the-other-side/${SERVICE_NAME}:latest"
SA="${SERVICE_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "◐ Deploying The Other Side to project: ${PROJECT_ID}"

# Enable required APIs
echo "→ Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  texttospeech.googleapis.com \
  storage.googleapis.com \
  firestore.googleapis.com \
  vision.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet

# Create GCS bucket if it doesn't exist
echo "→ Creating GCS bucket..."
gsutil mb -l ${REGION} gs://${BUCKET_NAME} 2>/dev/null || echo "  Bucket already exists, skipping."
gsutil iam ch allUsers:objectViewer gs://${BUCKET_NAME}

# Create service account if it doesn't exist
echo "→ Setting up service account..."
gcloud iam service-accounts create ${SERVICE_NAME}-sa \
  --display-name="The Other Side SA" 2>/dev/null || echo "  SA already exists, skipping."

for ROLE in \
  roles/aiplatform.user \
  roles/texttospeech.client \
  roles/storage.objectAdmin \
  roles/datastore.user \
  roles/cloudvision.admin; do
  gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA}" \
    --role="${ROLE}" \
    --quiet
done

# Build and push Docker image
echo "→ Building Docker image..."
gcloud builds submit \
  --tag ${IMAGE} \
  --machine-type=E2_HIGHCPU_8 \
  .

# Deploy to Cloud Run
echo "→ Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE} \
  --platform managed \
  --region ${REGION} \
  --service-account ${SA} \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET_NAME=${BUCKET_NAME},REGION=${REGION}" \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 10 \
  --allow-unauthenticated \
  --quiet

# Get the deployed URL
URL=$(gcloud run services describe ${SERVICE_NAME} \
  --platform managed \
  --region ${REGION} \
  --format "value(status.url)")

echo ""
echo "✅ Deployed successfully!"
echo "◐ Service URL: ${URL}"
echo ""
echo "Next steps:"
echo "  1. Update API_BASE in background.js to: ${URL}"
echo "  2. Update host_permissions in manifest.json to: ${URL}/*"
echo "  3. Reload the Chrome extension"
