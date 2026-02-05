#!/bin/bash

# =============================================================================
# Deploy Water Meter App to Google Cloud Run
# =============================================================================

set -e  # Exit on error

# Configuration
PROJECT_ID="water-meter-ocr-483703"
REGION="asia-southeast1"  # Bangkok region
SERVICE_NAME="water-meter-app"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "🚀 Deploying Water Meter App to Google Cloud Run"
echo "=================================================="
echo "Project ID: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service Name: ${SERVICE_NAME}"
echo ""

# Step 1: Set project
echo "📌 Step 1: Setting GCP project..."
gcloud config set project ${PROJECT_ID}

# Step 2: Build Docker image
echo "🔨 Step 2: Building Docker image..."
gcloud builds submit --tag ${IMAGE_NAME} .

# Step 3: Deploy to Cloud Run
echo "🚢 Step 3: Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --max-instances 10 \
  --set-env-vars "PORT=8080"

echo ""
echo "✅ Deployment completed!"
echo ""
echo "🌐 Your app is now available at:"
gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)'
