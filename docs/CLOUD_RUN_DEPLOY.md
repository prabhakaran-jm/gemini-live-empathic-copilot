# Cloud Run deployment – Empathic Co-Pilot backend

The backend (FastAPI + WebSocket `/ws`) runs on **Google Cloud Run**. This doc gives copy-paste steps for judges and deployers.

## Prerequisites

- **Google Cloud project** with billing enabled.
- **gcloud CLI** installed and logged in:
  ```bash
  gcloud auth login
  gcloud config set project YOUR_PROJECT_ID
  ```
- **APIs enabled** (deploy script uses Cloud Build; first deploy may prompt to enable APIs):
  - Cloud Run API
  - Cloud Build API
  - Artifact Registry (or Container Registry) for the image

## Deploy (copy-paste)

From the **repo root**:

**Bash (Linux / macOS / WSL):**
```bash
cd infra/cloudrun
chmod +x deploy.sh
./deploy.sh YOUR_PROJECT_ID us-central1
```

**PowerShell (Windows):**
```powershell
cd infra\cloudrun
.\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region us-central1
```

Or set env and run without args:
```bash
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export GOOGLE_CLOUD_REGION=us-central1
./deploy.sh
```

The script will:
1. Build the container with **Cloud Build** from `apps/server` (Dockerfile).
2. Deploy to **Cloud Run** with:
   - `--timeout 3600` (1 hour, for WebSocket)
   - `--min-instances 1` (demo stability)
   - Env: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_REGION`, `GEMINI_MODEL`, `BARGE_IN_RMS_THRESHOLD`

At the end it prints the **service URL** (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`).

## Environment variables on Cloud Run

Set by the deploy script (override via env before running the script if needed):

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | (from deploy) | GCP project ID (Vertex AI). |
| `GOOGLE_CLOUD_REGION` | `us-central1` | Region for Vertex AI. |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Gemini Live model. |
| `BARGE_IN_RMS_THRESHOLD` | `0.15` | RMS threshold for barge-in. |

**Auth on Cloud Run:** The service uses **Application Default Credentials** (ADC) in the Cloud Run environment, i.e. the service account of the Cloud Run service. Ensure that account has access to **Vertex AI** (e.g. "Vertex AI User" or appropriate role) in the same project.

**MOCK:** Do **not** set `MOCK=1` when deploying for real Gemini; leave unset for production.

## Connect the frontend to Cloud Run

After deploy you get a URL like:
`https://empathic-copilot-xxxxx-uc.a.run.app`

- **Health:** `https://YOUR_SERVICE_URL/health` → should return `{"status":"ok"}`.
- **WebSocket:** `wss://YOUR_SERVICE_URL/ws` (note **wss** when the page is served over https).

In the frontend, point the app at this backend:

- **Option A – Vite env:** Create `.env` in `apps/web`:
  ```
  VITE_WS_URL=wss://YOUR_SERVICE_URL/ws
  ```
  Then run `npm run dev` (or build and serve the SPA). The app will use this URL when not in mock mode.

- **Option B – Build and host:** Build the web app (`npm run build`), serve the `dist/` folder from any host (Firebase Hosting, Cloud Storage + Load Balancer, etc.), and set the same `VITE_WS_URL` at build time so the client connects to your Cloud Run `/ws`.

## Smoke test on Cloud Run

1. **Health check**
   ```bash
   curl -s https://YOUR_SERVICE_URL/health
   ```
   Expected: `{"status":"ok"}` with HTTP 200.

2. **WebSocket (quick check with a client)**
   - Open the frontend (with `VITE_WS_URL=wss://YOUR_SERVICE_URL/ws`), or
   - Use a WebSocket test tool (e.g. browser devtools or `wscat`) to connect to `wss://YOUR_SERVICE_URL/ws`, send `{"type":"start"}`, and confirm you get `{"type":"ready"}` (and then optional tension/whisper if mic is streaming).

3. **Logs**
   - In Google Cloud Console → **Cloud Run** → your service → **Logs**, confirm requests to `/health` and `/ws` and any application logs.

If any step fails, check **Cloud Run logs** and **IAM** (Vertex AI access for the Cloud Run service account).
