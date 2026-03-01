# Judges Quickstart

Short path to try Empathic Co-Pilot with the deployed backend or run it locally.

---

## Prerequisites

- **Browser** with microphone access (Chrome recommended).
- **Node.js** (v18+) and **npm** for running the frontend.
- (Option B only) **Google Cloud** project with billing, `gcloud` CLI, and Docker (or Cloud Build).
- (Option C only) **Python 3.10+** and optionally a Gemini API key or Vertex AI access.

---

## Option A: Use the deployed Cloud Run backend (recommended)

1. Get the Cloud Run URL from the team (e.g. `https://empathic-copilot-xxxxx-uc.a.run.app`).

2. **Health check**
   - Open `https://YOUR_CLOUD_RUN_URL/health` in a browser or run:
   - Mac/Linux: `curl https://YOUR_CLOUD_RUN_URL/health`
   - Windows (PowerShell): `Invoke-WebRequest -Uri "https://YOUR_CLOUD_RUN_URL/health" -UseBasicParsing`
   - Expect: `{"status":"ok"}`.

3. **Run the frontend** (from repo root):
   - Mac/Linux:
     ```bash
     cd apps/web && npm install && npm run dev
     ```
   - Windows (PowerShell):
     ```powershell
     cd apps\web; npm install; npm run dev
     ```
   - Point the app at the deployed backend (do this *before* `npm run dev`):
     - Mac/Linux: `export VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws`
     - Windows: `$env:VITE_WS_URL="wss://YOUR_CLOUD_RUN_URL/ws"`
   - Open http://localhost:5173.

4. **Test script**
   - Click **Start session**. Allow microphone when prompted. UI should show "Backend: Cloud Run" and session active.
   - **Transcript:** Speak normally (e.g. "I’m practicing a difficult conversation"). Within a few seconds you should see live transcript in the UI.
   - **Tension + whisper:** Raise your voice briefly (e.g. say something louder). The tension bar should increase; after a short delay you may see a coaching whisper (e.g. "Taking a breath before the next sentence can help.").
   - **Barge-in / interrupted:** While the agent is speaking (or during a period when it would be generating), keep talking or interrupt. In the **Event log** you should see an `event: interrupted` (or similar) entry.
   - There is no separate "Ask coach" button; coaching is triggered automatically by the backend from volume, silence, and overlap. Agent output is the live transcript plus these whisper lines.
   - Click **Stop session** when done.

---

## Option B: Deploy your own backend

Follow [DEPLOY.md](DEPLOY.md) to build and deploy the server (and optionally the frontend) to Cloud Run. Then use Option A steps 2–4 with your own Cloud Run URL.

---

## Option C: Local run (no Cloud Run)

**Mock mode (no Gemini, no API key):**

- Terminal 1 — backend:
  - Mac/Linux: `cd apps/server && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && MOCK=1 python run.py`
  - Windows: `cd apps\server; python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt; $env:MOCK="1"; python run.py`
- Terminal 2 — frontend: `cd apps/web && npm run dev` (no `VITE_WS_URL`; dev server proxies `/ws` to localhost).
- Open http://localhost:5173, click **Start session**. You’ll see fake tension and occasional whispers; no real transcript.

**Real mode (Gemini):** Same as above but omit `MOCK=1` and set either:
- `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_REGION` and use `gcloud auth application-default login` (Vertex AI), or  
- `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` (Gemini Developer API).

---

## Exact test script for judges

1. **Start** — Click **Start session**, allow mic. Confirm "Backend: Local" or "Backend: Cloud Run" and that the session is active (e.g. tension bar visible).
2. **Transcript** — Say: "I’m rehearsing a hard conversation with a colleague." Within ~5–10 s you should see your words in the Transcript area (when using real Gemini backend).
3. **Tension + whisper** — Speak a bit louder or more emphatically for a few seconds. Watch the tension bar; when it crosses upward, a whisper may appear (e.g. slow_down). Cooldown between whispers is ~12 s.
4. **Interrupted event** — Trigger agent output (e.g. ask a question that elicits a longer reply) or wait for a response; then talk over it. In the Event log, look for an entry like `event: interrupted`.
5. **Stop** — Click **Stop session**. Session should end cleanly; no further tension/whisper/transcript.

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| **No microphone** | Allow mic in browser (site settings or prompt). Use HTTPS or localhost. Check that no other app has exclusive access. |
| **WebSocket fails / wrong backend** | If using Cloud Run: set `VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws` (not `https`). Restart `npm run dev` after changing env. Check browser console for WS errors. |
| **403 or Vertex / Gemini errors** | Backend may lack Vertex AI permissions. On Cloud Run, the service account needs e.g. "Vertex AI User". See [DEPLOY.md](DEPLOY.md); deploy script prints the service account to grant. For local dev with API key, ensure `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` is set. |
| **No transcript, "Gemini unavailable" message** | Backend is in degraded mode (Gemini connect failed). You still get tension + whispers. Check backend logs and Vertex/API key configuration. |
| **Nothing happens on Start** | Confirm `/health` returns 200 for the backend you’re using. Check Event log for `ready` or `error` messages. Ensure WS URL is correct (e.g. `wss://` for HTTPS Cloud Run). |
