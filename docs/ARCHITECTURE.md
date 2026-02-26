# Empathic Co-Pilot – Architecture

## High-level flow

```
  ┌─────────────────┐     WebSocket (JSON)      ┌─────────────────┐
  │   Browser       │  ◄─────────────────────► │   Cloud Run     │
  │   (React/Vite)  │   /ws  audio, control      │   (FastAPI)     │
  │   Mic → PCM16   │   tension, whisper,       │   /health       │
  │   16kHz         │   transcript, events      │   /ws           │
  └────────┬────────┘                            └────────┬────────┘
           │                                               │
           │                                               │ Gemini Live API
           │                                               │ (bidi streaming)
           │                                               ▼
           │                                      ┌─────────────────┐
           │                                      │  Vertex AI      │
           │                                      │  Gemini Live    │
           │                                      │  (transcript,   │
           │                                      │   barge-in)     │
           │                                      └─────────────────┘
           │
           │  Optional: VITE_WS_URL points to Cloud Run URL (wss://...)
           ▼
  ┌─────────────────┐
  │  Local dev      │  Backend: python run.py (localhost:8765)
  │  or hosted SPA  │  Frontend: npm run dev (proxy /ws → backend)
  └─────────────────┘
```

## Components

| Component | Role |
|-----------|------|
| **Browser** | Captures mic (PCM16 16 kHz), sends base64 chunks + telemetry.rms over WebSocket; displays tension bar, live transcript, whispers, event log. |
| **Cloud Run (FastAPI)** | Accepts WebSocket at `/ws`; runs tension loop + deterministic whisper loop; optionally connects to Gemini Live; streams transcript and emits whispers from fixed coaching moves. |
| **Vertex AI / Gemini Live** | Real-time bidi audio/transcript; barge-in supported. When unavailable, backend runs in degraded mode (tension + whispers only, no transcript). |

## Deployment

- **Backend:** Single container on Cloud Run (see [CLOUD_RUN_DEPLOY.md](./CLOUD_RUN_DEPLOY.md)). Uses ADC for Vertex AI.
- **Frontend:** Static build; set `VITE_WS_URL=wss://YOUR_SERVICE_URL/ws` to target Cloud Run.

---

**TODO (Devpost):** Export a diagram as `docs/architecture.png` for submission (e.g. from this ASCII or a drawn version).
