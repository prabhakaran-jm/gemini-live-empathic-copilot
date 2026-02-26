# Empathic Co-Pilot

Empathic Co-Pilot is a real-time multimodal Live Agent built with **Gemini Live API on Google Cloud**. It augments difficult human conversations by providing subtle, interruptible whisper coaching based on conversational signals such as tone shifts, pauses, and turn-taking dynamics.  
Instead of replacing one side of the interaction, Empathic Co-Pilot acts as an invisible social prosthetic—supporting the user with grounded communication strategies derived from active listening and nonviolent communication principles.

The **backend** is hosted on **Google Cloud Run** and uses **Gemini Live via Vertex AI** for real-time audio and coaching.

## Key Features

🎙 Live bidirectional audio streaming (Gemini Live API)  
🔁 Interruptible coaching (barge-in support)  
📊 Real-time tension indicator  
🧠 Signal-based conversational analysis (volume spikes, silence, overlap)  
🎧 Whisper-style short coaching prompts  
☁ Hosted on Google Cloud (Cloud Run + Vertex AI)

## Architecture

Browser (Mic) → WebSocket → **Cloud Run** → Gemini Live API (Vertex AI) → Coaching Engine → Audio Whisper + Tension Bar UI

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for an ASCII diagram and component overview.

---

## Local development

**Backend (FastAPI + WebSocket):**
```bash
cd apps/server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
Server: `http://localhost:8765` · WebSocket: `ws://localhost:8765/ws`

**Frontend (React + Vite):**
```bash
cd apps/web
npm install
npm run dev
```
App: `http://localhost:5173` (proxies `/ws` and `/health` to the backend).

**Mock mode (no Gemini):** Run backend with `MOCK=1`; or run frontend with `VITE_USE_MOCK_WS=true` for in-browser mock only.

See [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) for full steps, env vars, and microphone setup.

---

## Cloud deployment (Cloud Run)

From the repo root:

**Bash:**
```bash
cd infra/cloudrun
./deploy.sh YOUR_PROJECT_ID us-central1
```

**PowerShell:**
```powershell
cd infra\cloudrun
.\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region us-central1
```

The script builds the container (Cloud Build), deploys to Cloud Run with WebSocket-friendly settings (timeout, min-instances), and sets env vars. It prints the service URL (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`).

**Connect the frontend:** Set `VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws` when running or building the web app so it uses the deployed backend.

See [docs/CLOUD_RUN_DEPLOY.md](docs/CLOUD_RUN_DEPLOY.md) for copy-paste steps and smoke test.

---

## Environment variables and auth

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (required for Vertex AI). |
| `GOOGLE_CLOUD_REGION` | Region (default `us-central1`). |
| `GEMINI_MODEL` | Gemini model (default `gemini-2.0-flash-exp`). |
| `BARGE_IN_RMS_THRESHOLD` | RMS threshold for barge-in (default `0.15`). |

**Auth (choose one):**

- **Vertex AI / ADC (preferred on GCP):** Set `GOOGLE_CLOUD_PROJECT` (and optionally `GOOGLE_CLOUD_REGION`). On your machine run `gcloud auth application-default login`. On **Cloud Run**, the service uses the default service account; ensure it has Vertex AI access (e.g. Vertex AI User).
- **API key (local dev):** Set `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` to use the Gemini Developer API instead of Vertex.

**MOCK:** Set `MOCK=1` to run the backend without Gemini (fake tension and whispers). Leave unset for production.

---

## Docs for judges

- [docs/CLOUD_RUN_DEPLOY.md](docs/CLOUD_RUN_DEPLOY.md) – Deploy steps and smoke test.
- [docs/PROOF_OF_DEPLOYMENT.md](docs/PROOF_OF_DEPLOYMENT.md) – Checklist for the proof video (Cloud Run service, logs, `/health`, UI → Cloud Run WebSocket).

---

## Why This Matters

Empathic Co-Pilot redefines AI interaction by moving beyond text chat into real-time conversational augmentation—helping users navigate difficult conversations with clarity and composure.
