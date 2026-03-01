# Deploy Empathic Co-Pilot backend to Cloud Run.
# Usage: .\deploy.ps1 [-ProjectId PROJECT_ID] [-Region REGION]
# Example: .\deploy.ps1 -ProjectId my-project -Region europe-west1

param(
    [string]$ProjectId = $env:GOOGLE_CLOUD_PROJECT,
    [string]$Region = $env:GOOGLE_CLOUD_REGION
)

if (-not $Region) { $Region = "europe-west1" }

$ServiceName = if ($env:CLOUD_RUN_SERVICE_NAME) { $env:CLOUD_RUN_SERVICE_NAME } else { "empathic-copilot" }
$GeminiModel = if ($env:GEMINI_MODEL) { $env:GEMINI_MODEL } else { "gemini-live-2.5-flash-native-audio" }
$BargeInRms = if ($env:BARGE_IN_RMS_THRESHOLD) { $env:BARGE_IN_RMS_THRESHOLD } else { "0.15" }
$TensionWhisperThreshold = if ($env:TENSION_WHISPER_THRESHOLD) { $env:TENSION_WHISPER_THRESHOLD } else { "24" }

if (-not $ProjectId) {
    Write-Error "Usage: .\deploy.ps1 -ProjectId PROJECT_ID [-Region REGION]"
    Write-Error "  or set env GOOGLE_CLOUD_PROJECT (and optionally GOOGLE_CLOUD_REGION)"
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$ServerDir = Join-Path $RepoRoot "apps\server"
$Image = "gcr.io/$ProjectId/${ServiceName}:latest"

Write-Host "Building and deploying to Cloud Run..."
Write-Host "  Project: $ProjectId"
Write-Host "  Region:  $Region"
Write-Host "  Service: $ServiceName"

# Build with Cloud Build
gcloud builds submit --tag $Image --project $ProjectId $ServerDir

# Deploy with WebSocket-friendly settings (concurrency 10 for WS stability).
# Optional: set CLOUD_RUN_GEN2=1 or CLOUD_RUN_CPU_BOOST=1 and add --execution-environment=gen2 or --cpu-boost to the command below.
gcloud run deploy $ServiceName `
  --image $Image `
  --platform managed `
  --region $Region `
  --project $ProjectId `
  --allow-unauthenticated `
  --timeout 3600 `
  --concurrency 10 `
  --min-instances 1 `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_REGION=$Region,GEMINI_MODEL=$GeminiModel,BARGE_IN_RMS_THRESHOLD=$BargeInRms,TENSION_WHISPER_THRESHOLD=$TensionWhisperThreshold"

$ServiceUrl = gcloud run services describe $ServiceName --region $Region --project $ProjectId --format="value(status.url)"
$SaEmail = gcloud run services describe $ServiceName --region $Region --project $ProjectId --format="value(spec.template.spec.serviceAccountName)"
if (-not $SaEmail) { $SaEmail = "(default compute SA)" }

Write-Host ""
Write-Host "Done. Service URL: $ServiceUrl"
Write-Host "Service account in use: $SaEmail"
Write-Host "  -> Ensure this identity has Vertex AI permissions (e.g. Vertex AI User) in project $ProjectId."
