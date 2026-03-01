# Empathic Co-Pilot – Architecture

## System Diagram

```mermaid
graph TB
    subgraph Browser ["Browser (React + Vite)"]
        MIC["Mic Capture<br/>PCM16 mono 16kHz"]
        UI["UI: Tension Bar, Whisper Box,<br/>Transcript, TTS Playback"]
    end

    subgraph CloudRun ["Google Cloud Run (FastAPI)"]
        WS["WebSocket /ws"]
        TL["Tension Loop<br/>RMS + Silence + Overlap → 0-100"]
        WL["Whisper Loop<br/>Triggers: tension ≥40,<br/>2+ barge-ins, post-escalation silence"]
    end

    subgraph GCP ["Google Cloud AI"]
        LIVE["Gemini Live API<br/>(bidi streaming)<br/>Transcription + Barge-in"]
        FLASH["Gemini 2.0 Flash<br/>(generate_content)<br/>NVC Coaching Whispers"]
    end

    MIC -- "audio chunks (base64) + telemetry" --> WS
    WS -- "tension, whisper, transcript" --> UI
    WS -- "PCM16 audio stream" --> LIVE
    LIVE -- "transcript deltas,<br/>agent state events" --> WS
    TL -- "trigger fired" --> WL
    WL -- "transcript + tension context" --> FLASH
    FLASH -- "8-12 word coaching whisper" --> WL

    style Browser fill:#1f6feb22,stroke:#58a6ff,color:#c9d1d9
    style CloudRun fill:#23863622,stroke:#3fb950,color:#c9d1d9
    style GCP fill:#f0883e22,stroke:#f0883e,color:#c9d1d9
```

## Components

| Component | Role |
|-----------|------|
| **Browser (React/Vite)** | Captures mic audio (PCM16 16kHz), sends base64 chunks + RMS telemetry via WebSocket. Displays tension bar, live transcript, coaching whispers. Speaks whispers aloud via Web Speech API. |
| **Cloud Run (FastAPI)** | Accepts WebSocket at `/ws`. Runs tension scoring loop (RMS, silence, overlap → 0-100). Runs whisper loop with 3 deterministic triggers. Streams audio to Gemini Live for transcription. Calls Gemini Flash for AI-generated coaching. |
| **Gemini Live API** | Real-time bidirectional audio streaming. Provides transcript deltas and supports barge-in (stop generation when user interrupts). |
| **Gemini 2.0 Flash** | Generates contextual 8-12 word coaching whispers grounded in NVC (Nonviolent Communication) and active listening. Called on-demand when tension triggers fire. Falls back to fixed phrases if unavailable. |

## Data Flow

1. **Audio In:** Browser captures mic → resamples to 16kHz PCM16 mono → base64-encodes → sends via WebSocket with RMS telemetry
2. **Tension Scoring:** Backend computes tension (0-100) from RMS volume, silence duration, and interruption overlap every 0.5s
3. **Transcription:** Backend streams PCM16 to Gemini Live API → receives transcript deltas → forwards to browser
4. **Barge-in:** When user speaks over agent output (RMS ≥ threshold), backend calls `stop_generation()` and emits `interrupted` event
5. **Coaching:** When a trigger fires (tension cross, barge-in count, post-escalation silence), backend sends transcript + tension context to Gemini Flash → receives contextual coaching whisper → sends to browser
6. **Audio Out:** Browser receives whisper text → speaks it aloud via Web Speech API (soft, slow voice)

## Deployment

- **Backend:** Single container on Cloud Run (see [CLOUD_RUN_DEPLOY.md](./CLOUD_RUN_DEPLOY.md)). Uses ADC for Vertex AI or API key.
- **Frontend:** Static build (`npm run build`). Set `VITE_WS_URL=wss://YOUR_SERVICE_URL/ws` to target Cloud Run.
- **IaC:** Deployment scripts at `infra/cloudrun/deploy.sh` (Bash) and `deploy.ps1` (PowerShell).
