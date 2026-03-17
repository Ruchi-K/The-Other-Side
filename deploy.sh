#!/bin/bash
set -e

PROJECT_ID="the-other-side-489308"
REGION="us-central1"
SERVICE_NAME="the-other-side"
BUCKET_NAME="${PROJECT_ID}-tos-videos"
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/the-other-side/${SERVICE_NAME}:latest"
SA="the-other-side-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "◐ Cleaning build context..."
touch __init__.py

echo "→ Building Docker image..."
gcloud builds submit --tag ${IMAGE} .

echo "→ Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE} \
  --platform managed \
  --region ${REGION} \
  --service-account ${SA} \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET_NAME=${BUCKET_NAME},REGION=${REGION}" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 600 \
  --cpu-boost \
  --allow-unauthenticated
