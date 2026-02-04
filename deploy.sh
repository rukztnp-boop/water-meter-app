#!/bin/bash
# Deploy to Google Cloud Run

echo "🚀 Deploying Water Meter App to Google Cloud Run..."

# Check if user provided PROJECT_ID
if [ -z "$1" ]; then
  echo "❌ Error: Please provide your Google Cloud PROJECT_ID"
  echo "Usage: ./deploy.sh YOUR_PROJECT_ID"
  echo ""
  echo "Example: ./deploy.sh my-project-123"
  exit 1
fi

PROJECT_ID=$1

echo "📦 Setting project to: $PROJECT_ID"
gcloud config set project $PROJECT_ID

echo "🏗️  Building and deploying to Cloud Run..."
gcloud run deploy water-meter-app \
  --source . \
  --platform managed \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 3600 \
  --max-instances 10

echo ""
echo "✅ Deployment complete!"
echo "🌐 Your app should be available at the URL shown above"
