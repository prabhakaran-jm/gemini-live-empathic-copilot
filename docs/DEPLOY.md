# Deploy frontend and backend

Deploy the **backend** to Cloud Run, then build and deploy the **frontend** with the backend URL baked in.

---

## Prerequisites

- **Google Cloud project** with billing enabled.
- **gcloud CLI** installed and logged in: `gcloud auth login`, `gcloud config set project YOUR_PROJECT_ID`.
- **APIs:** Cloud Run, Cloud Build (first deploy may prompt to enable them).

---

## 1. Backend (Cloud Run)

From the repo root.

**Mac/Linux (Bash):**
```bash
cd infra/cloudrun
./deploy.sh YOUR_PROJECT_ID europe-west1
```

**Windows (PowerShell):**
```powershell
cd infra\cloudrun
.\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region europe-west1
```

Replace `YOUR_PROJECT_ID` with your Google Cloud project ID. The script builds the image with Cloud Build, deploys to Cloud Run, and prints the **service URL**.

**Important:** Grant the Cloud Run service account **Vertex AI** access (e.g. "Vertex AI User"). The script prints the service account to use.

**Backend env vars** (set by the script; override via env before running if needed):

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLOUD_REGION` | `europe-west1` | Region for Vertex AI. |
| `GEMINI_MODEL` | `gemini-live-2.5-flash-native-audio` | Gemini Live model. |
| `BARGE_IN_RMS_THRESHOLD` | `0.15` | RMS threshold for barge-in. |
| `TENSION_WHISPER_THRESHOLD` | `24` | Tension score ≥ this triggers a whisper. |
| `COACHING_GROUNDING` | `0` | Set to `1`, `true`, or `yes` to enable Google Search grounding for coaching whispers (citations). |

**Verify:** `curl https://YOUR_SERVICE_URL/health` → expect `{"status":"ok"}`. Save the service URL for the frontend.

---

## 2. Frontend (build + host)

The frontend must be **built** with the backend WebSocket URL.

### Step A: Build with backend URL

**Mac/Linux:**
```bash
cd apps/web
export VITE_WS_URL=wss://YOUR_SERVICE_URL/ws
npm ci
npm run build
```

**Windows (PowerShell):**
```powershell
cd apps\web
$env:VITE_WS_URL = "wss://YOUR_SERVICE_URL/ws"
npm ci
npm run build
```

Replace `YOUR_SERVICE_URL` with the Cloud Run URL from step 1 (no trailing slash). Build output is in `apps/web/dist/`.

### Step B: Deploy the static site

**Firebase Hosting (recommended):** Enable the Firebase Hosting API and complete "Get started" in Firebase Console → Hosting if needed. Then:

```bash
npm install -g firebase-tools
firebase login
firebase use YOUR_PROJECT_ID
cd apps/web
firebase deploy --only hosting
```

Set `hosting.site` in `apps/web/firebase.json` to match your Firebase project/site ID. Firebase prints the Hosting URL.

**Other:** Upload `apps/web/dist/` to any static host (HTTPS required for microphone). SPA: unknown paths should serve `index.html`.

---

## 3. Smoke test and E2E

1. **Health:** `curl https://YOUR_SERVICE_URL/health` → `{"status":"ok"}`.
2. **Frontend:** Open the frontend URL; you should see "Backend: Cloud Run". Click **Start session**, allow mic; check Event log for `ready`, `tension`, and optionally `whisper`.
3. **Logs:** Cloud Console → Cloud Run → your service → Logs; confirm traffic while the session is active.

If the backend is unreachable, the UI may show "Gemini unavailable; running local coaching only". Confirm the Cloud Run URL and that `VITE_WS_URL` was set at **build** time.

---

## Quick reference

| Step | Where | Command / action |
|------|--------|-------------------|
| 1. Deploy backend | `infra/cloudrun` | `./deploy.sh PROJECT_ID europe-west1` (or `.ps1` on Windows) |
| 2a. Build frontend | `apps/web` | `VITE_WS_URL=wss://SERVICE_URL/ws npm run build` |
| 2b. Deploy frontend | `apps/web` | `firebase deploy --only hosting` (or upload `dist/` elsewhere) |
| 3. Test | Browser | Open frontend URL → Start session → use mic |

See [JUDGES_QUICKSTART.md](JUDGES_QUICKSTART.md) for a test script and troubleshooting.
