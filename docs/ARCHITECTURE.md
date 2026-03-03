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
        TL["Tension Loop<br/>RMS + Silence + Overlap + Semantic → 0-100"]
        WL["Whisper Loop<br/>Triggers: tension ≥threshold (24),<br/>2+ barge-ins, post-escalation silence"]
    end

    subgraph GCP ["Google Cloud AI"]
        LIVE["Gemini Live API<br/>(bidi streaming)<br/>Transcription + Barge-in"]
        FLASH["Gemini 2.0 Flash<br/>(generate_content)<br/>NVC Coaching Whispers"]
        LIVETTS["Gemini Live TTS<br/>(short-lived session)<br/>PCM16 mono 24kHz"]
    end

    MIC -- "audio chunks (base64) + telemetry" --> WS
    WS -- "tension, whisper text + audio_base64, transcript" --> UI
    WS -- "PCM16 audio stream" --> LIVE
    LIVE -- "transcript deltas,<br/>backchannel audio,<br/>agent state events" --> WS
    TL -- "trigger fired" --> WL
    WL -- "transcript + tension context" --> FLASH
    FLASH -- "8-12 word coaching whisper" --> WL
    WL -- "whisper text" --> LIVETTS
    LIVETTS -- "PCM24k base64 audio" --> WL
    WL -- "whisper msg (text + optional audio_base64)" --> WS

    style Browser fill:#1f6feb22,stroke:#58a6ff,color:#c9d1d9
    style CloudRun fill:#23863622,stroke:#3fb950,color:#c9d1d9
    style GCP fill:#f0883e22,stroke:#f0883e,color:#c9d1d9
```

## Components

| Component | Role |
|-----------|------|
| **Browser (React/Vite)** | Captures mic audio (PCM16 16kHz), sends base64 chunks + RMS telemetry via WebSocket. Displays tension bar, live transcript, coaching whispers. Plays whisper audio via Web Audio API (Gemini Live PCM24k) or Web Speech API fallback. Plays backchannel audio at low volume (0.18 gain) when received. |
| **Cloud Run (FastAPI)** | Accepts WebSocket at `/ws`. Runs tension scoring loop (RMS, silence, overlap, semantic escalation markers → 0-100). Runs whisper loop with 3 deterministic triggers. Streams audio to Gemini Live for transcription. Calls Gemini Flash for coaching text; when `COACHING_LIVE_AUDIO=1` (default), opens a short-lived Gemini Live TTS session to synthesize whisper audio (PCM24k). |
| **Gemini Live API** | Real-time bidirectional audio streaming. Provides transcript deltas, supports barge-in, and generates minimal empathetic backchannels ("Mmhm", "I see") when `LIVE_BACKCHANNEL=1` (default). |
| **Gemini Live TTS** | Short-lived Live session used only for coaching whisper synthesis. Receives whisper text from backend, returns PCM16 mono 24kHz audio; backend sends as `audio_base64` in whisper message. Disabled when `COACHING_LIVE_AUDIO=0`. |
| **Gemini 2.0 Flash** | Generates contextual 8-12 word coaching whispers grounded in NVC (Nonviolent Communication) and active listening. Called on-demand when tension triggers fire. Optional: Google Search grounding (env `COACHING_GROUNDING=1`) and vision (webcam frame as context). Falls back to fixed phrases if unavailable. |

## Data Flow

1. **Audio In:** Browser captures mic → resamples to 16kHz PCM16 mono → base64-encodes → sends via WebSocket with RMS telemetry
2. **Tension Scoring:** Backend computes tension (0-100) from RMS volume, silence duration, and interruption overlap every 0.5s
3. **Transcription:** Backend streams PCM16 to Gemini Live API → receives transcript deltas → forwards to browser
4. **Barge-in:** When user speaks over agent output (RMS ≥ threshold), backend calls `stop_generation()` and emits `interrupted` event
5. **Coaching:** When a trigger fires (tension cross, barge-in count, post-escalation silence), backend sends transcript + tension context to Gemini Flash → receives contextual coaching whisper → sends to browser
6. **Audio Out:** When `COACHING_LIVE_AUDIO=1` (default), backend opens a short-lived Gemini Live TTS session, sends coaching text, receives PCM16 mono 24kHz audio, and forwards it as `audio_base64` in the whisper message. Browser plays via Web Audio API; if absent or playback fails, falls back to Web Speech API (soft, slow voice).

## Deployment

- **Backend:** Single container on Cloud Run (see [DEPLOY.md](./DEPLOY.md)). Uses ADC for Vertex AI or API key.
- **Frontend:** Static build (`npm run build`). Set `VITE_WS_URL=wss://YOUR_SERVICE_URL/ws` to target Cloud Run.
- **IaC:** Deployment scripts at `infra/cloudrun/deploy.sh` (Bash) and `deploy.ps1` (PowerShell).
