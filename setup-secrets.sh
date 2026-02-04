#!/bin/bash
# Set secrets for Cloud Run

echo "🔐 Setting up secrets for Cloud Run..."

if [ -z "$1" ]; then
  echo "❌ Error: Please provide your Google Cloud PROJECT_ID"
  echo "Usage: ./setup-secrets.sh YOUR_PROJECT_ID"
  exit 1
fi

PROJECT_ID=$1

echo "Creating secrets from service_account.json..."
gcloud secrets create service-account-json \
  --data-file=service_account.json \
  --project=$PROJECT_ID

echo "✅ Secrets created!"
echo "Note: Make sure to mount these secrets in Cloud Run deployment"
