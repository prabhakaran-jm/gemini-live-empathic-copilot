#!/usr/bin/env bash
# Deploy Empathic Co-Pilot backend to Cloud Run.
# Usage: ./deploy.sh [PROJECT_ID] [REGION]
# Example: ./deploy.sh my-project europe-west1

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVER_DIR="$REPO_ROOT/apps/server"
SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-empathic-copilot}"

PROJECT_ID="${1:-$GOOGLE_CLOUD_PROJECT}"
REGION="${2:-${GOOGLE_CLOUD_REGION:-europe-west1}}"

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: $0 PROJECT_ID [REGION]"
  echo "  or set GOOGLE_CLOUD_PROJECT and optionally GOOGLE_CLOUD_REGION"
  exit 1
fi

echo "Building and deploying to Cloud Run..."
echo "  Project: $PROJECT_ID"
echo "  Region:  $REGION"
echo "  Service: $SERVICE_NAME"

# Build with Cloud Build (pushes to Artifact Registry / GCR)
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" "$SERVER_DIR"

# Optional: Gen2 and CPU boost (set CLOUD_RUN_GEN2=1, CLOUD_RUN_CPU_BOOST=1 to enable)
EXTRA_FLAGS=()
[ "${CLOUD_RUN_GEN2}" = "1" ] && EXTRA_FLAGS+=(--execution-environment=gen2)
[ "${CLOUD_RUN_CPU_BOOST}" = "1" ] && EXTRA_FLAGS+=(--cpu-boost)

# Deploy with WebSocket-friendly settings (concurrency 10 for WS stability)
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --allow-unauthenticated \
  --timeout 3600 \
  --concurrency 10 \
  --min-instances 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_REGION=${REGION},GEMINI_MODEL=${GEMINI_MODEL:-gemini-live-2.5-flash-native-audio},BARGE_IN_RMS_THRESHOLD=${BARGE_IN_RMS_THRESHOLD:-0.15}" \
  "${EXTRA_FLAGS[@]}"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
SA_EMAIL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(spec.template.spec.serviceAccountName)')
[ -z "$SA_EMAIL" ] && SA_EMAIL="default compute SA"

echo ""
echo "Done. Service URL: $SERVICE_URL"
echo "Service account in use: $SA_EMAIL"
echo "  -> Ensure this identity has Vertex AI permissions (e.g. Vertex AI User) in project $PROJECT_ID."
