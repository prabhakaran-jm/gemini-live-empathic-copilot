# Empathic Co-Pilot – WebSocket Message Protocol

All messages are JSON over a single WebSocket connection (client ↔ our backend).  
Our backend speaks this protocol with the browser and (separately) with Gemini Live API.

---

## Tech Stack

| Layer        | Choice        | Notes                                      |
|-------------|---------------|--------------------------------------------|
| Frontend    | React 18 + Vite | SPA, minimal deps                          |
| Backend     | FastAPI       | Native WebSocket, async, Cloud Run–ready   |
| Transport   | JSON over WS  | One connection: audio chunks + control     |
| Gemini      | Live API      | Bidi streaming (to be wired in backend)    |

---

## Message Types (Browser ↔ Our Backend)

### Client → Server (browser sends)

| `type`        | Description        | Payload |
|---------------|--------------------|---------|
| `start`       | Start session      | `{}` or optional `{ "config": {} }` |
| `stop`        | End session        | `{}` |
| `audio`       | Raw audio chunk    | `{ "base64": "<base64 PCM>" }` (e.g. 16 kHz, 16-bit mono). Optional: `telemetry`: `{ "rms": number }`. |

### Server → Client (backend sends)

| `type`           | Description              | Payload |
|------------------|--------------------------|---------|
| `ready`          | Session ready            | `{}` |
| `tension`        | Updated tension score    | `{ "score": number 0–100, "ts": number }` |
| `transcript`     | Live transcript delta    | `{ "delta": string, "ts": number }` |
| `whisper`        | Coaching whisper (text)   | `{ "text": string, "move": string, "ts": number }` |
| `error`          | Error                    | `{ "message": string }` |
| `event`          | Client event (e.g. barge-in) | `{ "name": string, "ts": number }` e.g. `name: "interrupted"` |
| `stopped`        | Session ended            | `{}` |

- All server messages that carry a timestamp use `ts` as Unix milliseconds (optional but recommended for logs).
- Client `audio` messages may include optional `telemetry`: `{ "rms": number }` (0–1) for backend tension and barge-in.

---

## Coaching Moves (exactly 5)

Whispers are **only** from this set; each move has a fixed 8–12 word phrase (cautious, no diagnosis).

| `move`            | Example phrase (8–12 words) |
|-------------------|-----------------------------|
| `reflect_back`    | "It sounds like this is really important to you right now." |
| `clarify_intent`  | "Would it help to say what you're hoping they take away?" |
| `slow_down`       | "Taking a breath before the next sentence can help." |
| `deescalate_tone` | "A softer tone might make it easier for them to hear you." |
| `invite_perspective` | "You could ask how they're seeing it so far." |

---

## Audio Format (for MVP)

- **Encoding:** 16-bit PCM, mono.
- **Sample rate:** 16000 Hz (matches common Gemini Live expectations).
- **Chunk:** Base64-encoded; typical chunk ~20–40 ms for low latency.

---

## Barge-in (backend behavior)

- When the server receives `audio` while the agent is generating a response, it MUST:
  1. Stop sending current generation to the client.
  2. (TODO) Signal Gemini to cancel/trim and resume from new user audio.
- The client only sends `audio`; barge-in logic lives in the backend and Gemini session.

---

## Example Flows

**Start**
```json
C→S: { "type": "start" }
S→C: { "type": "ready" }
```

**Tension update**
```json
S→C: { "type": "tension", "score": 42, "ts": 1730000000000 }
```

**Whisper**
```json
S→C: { "type": "whisper", "text": "It sounds like this is really important to you right now.", "move": "reflect_back", "ts": 1730000001000 }
```

**Stop**
```json
C→S: { "type": "stop" }
S→C: { "type": "stopped" }
```
