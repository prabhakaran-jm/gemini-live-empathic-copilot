# Empathic Co-Pilot

Empathic Co-Pilot is a real-time multimodal Live Agent built with **Gemini Live API on Google Cloud**. It augments difficult human conversations by providing subtle, interruptible whisper coaching based on conversational signals such as tone shifts, pauses, and turn-taking dynamics.  
Instead of replacing one side of the interaction, Empathic Co-Pilot acts as an invisible social prosthetic—supporting the user with grounded communication strategies derived from active listening and nonviolent communication principles.

The **backend** is hosted on **Google Cloud Run** and uses **Gemini Live via Vertex AI** for real-time audio and coaching.

---

## 1-Minute Quickstart (Judges)

**(a) Health check** — In a browser or terminal:
```bash
curl https://YOUR_CLOUD_RUN_URL/health
```
Expect `{"status":"ok"}`.

**(b) Run the frontend** — From repo root:
- Mac/Linux: `cd apps/web && npm install && npm run dev`
- Windows (PowerShell): `cd apps\web; npm install; npm run dev`

To use the deployed backend, set the WebSocket URL before starting (Mac/Linux: `export VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws` then `npm run dev`; Windows: `$env:VITE_WS_URL="wss://YOUR_CLOUD_RUN_URL/ws"; npm run dev`).

**(c) What to do** — Open the app (e.g. http://localhost:5173), click **Start session**, allow mic. **Look for:** live **Transcript**, **Tension** bar, **Whisper** coaching lines, and **Event** log entries (e.g. `interrupted` when you talk over the agent). Click **Stop session** when done.

Full steps: [docs/JUDGES_QUICKSTART.md](docs/JUDGES_QUICKSTART.md).

---

## Key Features

🎙 Live bidirectional audio streaming (Gemini Live API)  
🔁 Interruptible coaching (barge-in support)  
📊 Real-time tension indicator  
🧠 Signal-based conversational analysis (volume spikes, silence, overlap)  
🎧 Whisper-style short coaching prompts  
☁ Hosted on Google Cloud (Cloud Run + Vertex AI)

**What's implemented in MVP (locked scope):** WebSocket session start/stop; mic → PCM 16 kHz → backend; tension score from RMS/silence/overlap; deterministic whisper rules (tension cross → slow_down, 2× barge-in → reflect_back, post-escalation silence → clarify_intent); live transcript via Gemini Live; barge-in detection and `event: interrupted`; degraded mode when Gemini is unavailable (tension + whispers only); Cloud Run deploy with health check; frontend backend indicator (Local / Cloud Run). **Optional:** webcam (vision) for context-aware coaching; Google Search grounding for coaching (env `COACHING_GROUNDING=1`).

**Degraded mode:** If Gemini Live connect fails (auth, quota, or model error), the session does not fail. The backend runs in "local-only" mode: tension updates and the whisper loop keep running; transcript streaming is disabled. The client receives one `error` message: "Gemini unavailable; running local coaching only." Stop/cleanup works as usual.

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
./deploy.sh YOUR_PROJECT_ID europe-west1
```

**PowerShell:**
```powershell
cd infra\cloudrun
.\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region europe-west1
```

The script builds the container (Cloud Build), deploys to Cloud Run with WebSocket-friendly settings (timeout, min-instances), and sets env vars. It prints the service URL (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`).

**Connect the frontend:** Set `VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws` when running or building the web app so it uses the deployed backend.

See [docs/DEPLOY.md](docs/DEPLOY.md) for copy-paste steps (backend + frontend) and smoke test.

---

## Environment variables and auth

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (required for Vertex AI). |
| `GOOGLE_CLOUD_REGION` | Region (default `europe-west1`; must be a [Live model–supported region](https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-live-api)). |
| `GEMINI_MODEL` | Gemini Live model (default `gemini-live-2.5-flash-native-audio`). |
| `BARGE_IN_RMS_THRESHOLD` | RMS threshold for barge-in (default `0.15`). |

**Auth (choose one):**

- **Vertex AI / ADC (preferred on GCP):** Set `GOOGLE_CLOUD_PROJECT` (and optionally `GOOGLE_CLOUD_REGION`). On your machine run `gcloud auth application-default login`. On **Cloud Run**, the service uses the default service account; ensure it has Vertex AI access (e.g. Vertex AI User).
- **API key (local dev):** Set `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` to use the Gemini Developer API instead of Vertex.

**MOCK:** Set `MOCK=1` to run the backend without Gemini (fake tension and whispers). Leave unset for production.

---

## Docs for judges

- [docs/JUDGES_QUICKSTART.md](docs/JUDGES_QUICKSTART.md) – Health check, run frontend, test script, troubleshooting.
- [docs/DEPLOY.md](docs/DEPLOY.md) – Deploy backend + frontend, smoke test.

---

## Why This Matters

Empathic Co-Pilot redefines AI interaction by moving beyond text chat into real-time conversational augmentation—helping users navigate difficult conversations with clarity and composure.
