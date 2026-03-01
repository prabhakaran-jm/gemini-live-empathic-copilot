# Local development – Empathic Co-Pilot MVP

## Step-by-step plan

1. **Tech stack & protocol**  
   See [PROTOCOL.md](./PROTOCOL.md): React (Vite) + FastAPI, JSON over WebSocket.

2. **Scaffold**  
   Repo layout:
   - `apps/web` – React + Vite frontend
   - `apps/server` – FastAPI backend

3. **Backend**  
   WebSocket at `/ws`, stub `GeminiLiveClient`, tension from telemetry, 5 coaching moves.

4. **Frontend**  
   Start/Stop, tension bar, event log; optional mock mode (no server).

---

## Commands (two terminals)

### Terminal 1 – Backend

```powershell
cd apps\server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

On macOS/Linux use `source .venv/bin/activate` instead of `.venv\Scripts\activate`.

Server runs at **http://localhost:8765**. WebSocket: **ws://localhost:8765/ws**.

### Environment variables (real Gemini Live)

| Variable | Description |
|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (for Vertex AI). |
| `GOOGLE_CLOUD_REGION` | Region (default `europe-west1`). |
| `GEMINI_MODEL` | Gemini Live model (default `gemini-live-2.5-flash-native-audio`). |
| `GOOGLE_GENAI_API_KEY` or `GEMINI_API_KEY` or `GOOGLE_API_KEY` | API key for Gemini Developer API (alternative to Vertex). |

**Authentication:** Use either (1) **Vertex AI** with Application Default Credentials (ADC): set `GOOGLE_CLOUD_PROJECT` and optionally `GOOGLE_CLOUD_REGION`, and run where ADC is available (e.g. `gcloud auth application-default login`), or (2) **API key**: set one of the API key env vars above.

**Barge-in:** When user audio RMS exceeds `BARGE_IN_RMS_THRESHOLD` (default `0.15`) while the agent is speaking, the server calls `stop_generation()` and sends `{ "type": "event", "name": "interrupted" }` to the frontend.

**Mock mode (no Gemini):**  
```powershell
$env:MOCK=1; python run.py
```
Then start the frontend; the server will send fake tension + whispers.

### Terminal 2 – Frontend

```powershell
cd apps\web
npm install
npm run dev
```

App runs at **http://localhost:5173**. Vite proxies `/ws` and `/health` to the backend (port 8765).

**Frontend-only (no backend):**  
```powershell
$env:VITE_USE_MOCK_WS="true"; npm run dev
```
Uses an in-browser mock: no server needed; tension and whispers are simulated. In mock mode the app does **not** request microphone access.

### Microphone and audio format

When not using mock mode, **Start session** will request browser microphone permission. Allow access so the app can stream live audio to the backend.

- **Format sent to backend:** PCM 16-bit mono, 16 kHz, base64-encoded in WebSocket messages `{ type: "audio", base64: "<...>", telemetry?: { rms } }`.
- **Chunk size:** 20–40 ms (configurable in `src/audioCapture.js`). Typical chunk is ~640 bytes (40 ms at 16 kHz).
- **RMS:** The frontend computes RMS per chunk (0–1) and sends it in `telemetry.rms`; the **Mic (RMS)** bar in the UI helps calibrate input level.
- **HTTPS / localhost:** `getUserMedia` requires a secure context (https or localhost). For local dev, use `http://localhost:5173`.

---

## Files created (initial layout)

```
apps/
  server/
    app/
      __init__.py
      main.py           # FastAPI app, /health, /ws
      websocket_handler.py
      gemini_live_client.py   # Stub + interfaces
      tension.py        # Deterministic tension score
      coaching.py       # 5 fixed moves
    requirements.txt
    run.py
  web/
    src/
      main.jsx
      App.jsx           # Start/Stop, tension bar, whisper box, logs
      App.css
      useWebSocket.js   # WS hook + optional mock
      index.css
    index.html
    package.json
    vite.config.js      # Proxy /ws, /health → 8765
docs/
  PROTOCOL.md
  LOCAL_DEV.md
```

---

## Smoke test (Gemini Live only)

From `apps/server` with venv activated and credentials set:

```powershell
$env:GOOGLE_CLOUD_PROJECT="your-project-id"
$env:GOOGLE_CLOUD_REGION="europe-west1"
python -m scripts.smoke_test
```

Or with API key:

```powershell
$env:GOOGLE_GENAI_API_KEY="your-api-key"
python -m scripts.smoke_test
```

The script opens a Live session, sends ~1s of silent PCM16 16 kHz in chunks, and prints received events (transcript_delta, agent_output_started/stopped, error). No UI.

---

## Quick test

1. **With backend:** Terminal 1 run server (optionally `MOCK=1`), Terminal 2 run `npm run dev`. Open http://localhost:5173 → Start session → see tension bar and event log; mock server sends tension + whispers every few seconds.
2. **Frontend only:** Terminal 2 run `VITE_USE_MOCK_WS=true npm run dev` → Start session → same UI with in-browser mock.

### Verify real mode (MOCK off)

1. **Transcript:** Start session (real backend, no `MOCK=1`), allow mic, speak. The **Live Transcript** panel should append text as the model transcribes. Event log stays separate (no transcript flooding).
2. **Whispers:** Deterministic triggers (12s cooldown): (a) tension crosses up into ≥ threshold (default 24) → *slow_down*; (b) ≥2 barge-in events in last 5s → *reflect_back*; (c) silence >2.5s and tension was ≥70 in last 10s → *clarify_intent*. Run a scripted scenario (e.g. speak, then stay silent >2.5s after a tense moment) to see a whisper.
3. **Barge-in:** While the agent is speaking (transcript or TTS), talk over it; the **Event log** should show an `event` `interrupted` entry, and the agent should stop.

---

## Next steps (post-MVP)

- Optional: TTS for whispers.
