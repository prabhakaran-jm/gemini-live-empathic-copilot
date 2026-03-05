# Empathic Co-Pilot

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Google%20Cloud%20Run-blue.svg)](https://cloud.google.com/run)
[![Gemini](https://img.shields.io/badge/AI-Gemini%20Live%20API-4285F4.svg)](https://ai.google.dev/)
[![Vertex AI](https://img.shields.io/badge/Vertex%20AI-Live%20Agent-8E24AA.svg)](https://cloud.google.com/vertex-ai)

Empathic Co-Pilot is a real-time multimodal **Live Agent** (Gemini Live Agent Challenge) built with the **Gemini Live API** on **Google Cloud**. It augments difficult human conversations by providing subtle, interruptible whisper coaching based on conversational signals such as tone shifts, pauses, and turn-taking dynamics.  
Instead of replacing one side of the interaction, Empathic Co-Pilot acts as an invisible social prosthetic—supporting the user with grounded communication strategies derived from active listening and nonviolent communication principles.

The **backend** is hosted on **Google Cloud Run** and uses **Gemini Live via Vertex AI** for real-time audio. The coaching persona **"Sage"** — a calm, emotionally intelligent mentor — whispers NVC-grounded guidance through **Gemini Live TTS** (Puck voice), producing natural human-like speech rather than robotic synthesis.

> **Challenge alignment:** Uses **Gemini Live API** (real-time bidirectional audio, interruptible); **Google GenAI SDK** (google-genai); **Google Cloud** (Cloud Run, Vertex AI, Cloud TTS, Cloud STT, Cloud Build); **multimodal** (audio stream + webcam vision for body-language-aware coaching + Google Search grounding). No text-in/text-out—full duplex audio with vision-aware, evidence-grounded coaching.

---

## ⚡ 1-Minute Quickstart (Judges)

**(a) Health check** — In a browser or terminal:
```bash
curl https://empathic-copilot-750378193246.europe-west1.run.app/health
```
Expect `{"status":"ok"}`.

**(b) Run the frontend** — From repo root:
- Mac/Linux: `cd apps/web && npm install && npm run dev`
- Windows (PowerShell): `cd apps\web; npm install; npm run dev`

To use the deployed backend, set the WebSocket URL before starting (Mac/Linux: `export VITE_WS_URL=wss://empathic-copilot-750378193246.europe-west1.run.app/ws` then `npm run dev`; Windows: `$env:VITE_WS_URL="wss://empathic-copilot-750378193246.europe-west1.run.app/ws"; npm run dev`).

**(c) What to do** — Open the app (e.g. http://localhost:5173), click **Start session**, allow mic. **Look for:** live **Transcript**, **Tension** bar, and **Whisper** coaching lines. Add `?debug=1` to the URL to show the **Advanced** section (RMS) and **Event log**. Click **Stop session** when done.

Full steps: [docs/JUDGES_QUICKSTART.md](docs/JUDGES_QUICKSTART.md).

---

## 🎯 Key Features

🎙 **Live bidirectional audio streaming** (Gemini Live API) with empathetic backchanneling
📷 **Vision-aware coaching** — optional webcam for body-language-aware whispers  
🔁 **Interruptible coaching** (barge-in support)  
📊 **Real-time tension indicator** (4 signals: volume, silence, interruptions, escalation language)  
🧠 **Signal-based conversational analysis** (volume, silence, overlap, semantic markers)  
🎧 **Natural whisper coaching** via Gemini Live TTS (Puck voice) — human-like speech, not robotic synthesis  
🔍 **Google Search grounding** for evidence-based coaching (NVC + conflict resolution research)  
☁ **Hosted on Google Cloud** (Cloud Run + Vertex AI + Cloud TTS + Cloud STT)

**What's implemented:** WebSocket session start/stop; mic → PCM 16 kHz → backend; tension score from RMS/silence/overlap/semantic markers; deterministic whisper rules (tension cross, 2× barge-in, post-escalation silence); live transcript via Gemini Live + Cloud STT streaming fallback; barge-in detection and `event: interrupted`; degraded mode when Gemini is unavailable (tension + whispers only); Cloud Run deploy with health check; webcam vision for body-language-aware coaching; Google Search grounding for evidence-based coaching (`COACHING_GROUNDING=1` enabled by default); Gemini Live TTS whisper and backchannel audio (Puck voice with whisper post-processing, Cloud TTS Studio-O fallback).

> **Degraded mode:** If Gemini Live connect fails (auth, quota, or model error), the session does not fail. The backend runs in "local-only" mode: tension updates and the whisper loop keep running; transcript streaming is disabled. The client receives one `error` message: "Gemini unavailable; running local coaching only." Stop/cleanup works as usual.

## 🔄 How It Works

1. **You talk** — The mic picks up your conversation in real time and sends audio to the backend. Optionally, your webcam captures body language.
2. **Sage listens** — Gemini transcribes your speech while a tension engine scores volume, silence, interruptions, and escalation language.
3. **Sage whispers** — When tension rises, Gemini Flash generates a calm coaching tip (grounded in NVC research via Google Search) and Sage speaks it softly through your speakers using Gemini Live TTS (Puck voice) — natural, human-like whisper audio.

## 🏗️ Architecture

```
Browser (Mic) → WebSocket → Cloud Run → Gemini Live API (Vertex AI) → Coaching Engine → Audio Whisper + Tension Bar UI
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for an ASCII diagram and component overview.

---

## 🛠️ Local Development

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

## ☁️ Cloud Deployment (Cloud Run)

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

## ⚙️ Environment Variables & Auth

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (required for Vertex AI). |
| `GOOGLE_CLOUD_REGION` | Vertex AI region (default `us-central1` so Gemini Live `session.receive()` gets messages; use `europe-west1` for EU data residency if needed). |
| `GEMINI_MODEL` | Gemini Live model (default `gemini-live-2.5-flash-native-audio`). Requires `google-genai>=1.50.0`. |
| `TENSION_WHISPER_THRESHOLD` | Tension score (0–100) above which a coaching whisper is triggered (default `20`). |
| `BARGE_IN_RMS_THRESHOLD` | RMS threshold for barge-in (default `0.15`). |
| `COACHING_GROUNDING` | Set to `1` (default) to enable Google Search grounding for coaching (NVC/conflict resolution research). Set to `0` to disable. |
| `LIVE_BACKCHANNEL` | Set to `1` (default) to enable empathetic backchanneling ("Ok.", "I see.") via Gemini Live TTS (same Puck voice as whisper). Set to `0` for silent transcription only. |
| `GEMINI_RECONNECT` | Set to `1` (default) to attempt reconnecting the Gemini Live session when the recv stream drops; set to `0` to stay in degraded mode only. |
| `LIVE_STT_STREAMING` | Set to `1` (default) to use Cloud Speech-to-Text streaming for **live transcription as you speak** when Gemini Live does not emit transcript. Set to `0` to use batch fallback only. |

**Auth (choose one):**

- **Vertex AI / ADC (preferred on GCP):** Set `GOOGLE_CLOUD_PROJECT` (and optionally `GOOGLE_CLOUD_REGION`). On your machine run `gcloud auth application-default login`. On **Cloud Run**, the service uses the default service account; ensure it has Vertex AI access (e.g. Vertex AI User).
- **API key (local dev):** Set `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` to use the Gemini Developer API instead of Vertex.

**MOCK:** Set `MOCK=1` to run the backend without Gemini (fake tension and whispers). Leave unset for production.

---

## 📚 Docs for Judges

| Doc | Description |
|-----|-------------|
| [JUDGES_QUICKSTART.md](docs/JUDGES_QUICKSTART.md) | Health check, run frontend, test script, backchannel note, troubleshooting. |
| [DEPLOY.md](docs/DEPLOY.md) | Deploy backend + frontend, smoke test. |

---

## 💡 Why This Matters

Empathic Co-Pilot redefines AI interaction by moving beyond text chat into real-time conversational augmentation—helping users navigate difficult conversations with clarity and composure.

---
*Built for the **Gemini Live Agent Challenge** — real-time, multimodal coaching at the edge of the conversation.*
