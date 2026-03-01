# Deploy frontend and backend

Deploy the **backend** to Cloud Run, then build and deploy the **frontend** with the backend URL baked in.

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
.\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region us-central1
```

Replace `YOUR_PROJECT_ID` with your Google Cloud project ID. The script will:

- Build the server image with Cloud Build
- Deploy to Cloud Run and print the **service URL** (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`)

**Important:** Grant the Cloud Run service account **Vertex AI** access (e.g. “Vertex AI User”) in the same project. The script prints the service account to use.

**Verify:**
```bash
curl https://YOUR_SERVICE_URL/health
```
Expected: `{"status":"ok"}`.

Save the service URL; you need it for the frontend (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`).

---

## 2. Frontend (build + host)

The frontend must be **built** with the backend WebSocket URL so the app knows where to connect.

### Step A: Build with backend URL

From the repo root.

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

Replace `YOUR_SERVICE_URL` with the Cloud Run URL from step 1 (no trailing slash). Example: if the URL is `https://empathic-copilot-xxxxx-uc.a.run.app`, then `VITE_WS_URL=wss://empathic-copilot-xxxxx-uc.a.run.app/ws`.

The build output is in `apps/web/dist/`.

### Step B: Deploy the static site

Choose one option.

#### Option 1: Firebase Hosting (recommended, same GCP project)

**First-time setup:** Enable the Firebase Hosting API for your project (e.g. [enable in Cloud Console](https://console.cloud.google.com/apis/library/firebasehosting.googleapis.com) or `gcloud services enable firebasehosting.googleapis.com --project=YOUR_PROJECT_ID`). Then in [Firebase Console](https://console.firebase.google.com) open your project, go to **Build → Hosting** and click **Get started** to create the default site. The default site ID is your project ID. Set `hosting.site` in `apps/web/firebase.json` to match. If `firebase init` or deploy returns 404 "Requested entity was not found", enable the Hosting API and complete "Get started" in Hosting first.

1. Install Firebase CLI (once): `npm install -g firebase-tools`
2. Log in and select project:
   ```bash
   firebase login
   firebase use YOUR_PROJECT_ID
   ```
3. From **apps/web** (after building):
   ```bash
   cd apps/web
   firebase deploy --only hosting
   ```
   On first run you may be asked to create a Firebase project or link an existing one; choose the same project as Cloud Run.  
   **If you use a different GCP/Firebase project:** in `apps/web/firebase.json` set `hosting.site` to that project ID (the default Firebase site name is the project ID).

4. Firebase prints a **Hosting URL** (e.g. `https://YOUR_PROJECT_ID.web.app`). Open it; the app will connect to your Cloud Run backend via the baked-in `VITE_WS_URL`.

**SPA routing:** `apps/web/firebase.json` is set up so all routes serve `index.html`.

#### Option 2: Other static hosting

Upload the contents of `apps/web/dist/` to any static host (e.g. Netlify, Vercel, Cloud Storage + Load Balancer, or your own server). Ensure:

- The site is served over **HTTPS** (required for microphone in browsers).
- No redirects or rewrites break the single-page app (unknown paths should serve `index.html` if you use client-side routing later).

---

## 3. End-to-end check

1. Open the **frontend URL** (Firebase Hosting or your host).
2. You should see “Backend: Cloud Run” in the UI.
3. Click **Start session**, allow the microphone.
4. Speak; you should see transcript (if Gemini is connected), tension bar, and possibly whispers. Check the Event log for messages.

If the backend is unreachable, the UI may show an error or “Gemini unavailable; running local coaching only” (degraded mode). Confirm the Cloud Run URL and that `VITE_WS_URL` was set at **build** time.

---

## Quick reference

| Step | Where | Command / action |
|------|--------|--------------------|
| 1. Deploy backend | `infra/cloudrun` | `./deploy.sh PROJECT_ID europe-west1` (or `.ps1` on Windows) |
| 2a. Build frontend | `apps/web` | `VITE_WS_URL=wss://SERVICE_URL/ws npm run build` |
| 2b. Deploy frontend | `apps/web` | `firebase deploy --only hosting` (or upload `dist/` elsewhere) |
| 3. Test | Browser | Open frontend URL → Start session → use mic |

See [CLOUD_RUN_DEPLOY.md](CLOUD_RUN_DEPLOY.md) for backend details and [JUDGES_QUICKSTART.md](JUDGES_QUICKSTART.md) for testing.
