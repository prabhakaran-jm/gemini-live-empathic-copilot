# Proof Video – What to Record

Step-by-step checklist for recording the Devpost proof video.

---

## 1. Cloud Run service (console)

- Open **Google Cloud Console** → **Cloud Run**.
- Select the Empathic Co-Pilot service.
- Show **Service details**: URL, region, status **Serving**.
- Optional: show env vars (e.g. `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_REGION`).

**Asset:** Screenshot can be saved as `docs/proof/cloudrun_logs.png` (or a dedicated service-details screenshot).

---

## 2. Health endpoint

- In browser or terminal, open: `https://YOUR_CLOUD_RUN_URL/health`.
- Show response: HTTP 200, body `{"status":"ok"}`.

---

## 3. Cloud Run logs (active session)

- In Cloud Run → same service → **Logs** tab.
- Start a session from the app (frontend connected to this Cloud Run URL).
- Show log entries while the session is active (e.g. WebSocket, requests, app logs).

**Asset:** Screenshot of logs → `docs/proof/cloudrun_logs.png` (or `cloudrun_service.png` for step 1, `cloudrun_logs.png` for this step).

---

## 4. UI → Cloud Run WebSocket

- Open the Empathic Co-Pilot frontend with `VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws`.
- Click **Start session**, allow mic.
- Show: **Backend: Cloud Run**, session active, tension bar, transcript (if Gemini is connected), Event log with incoming messages.
- Optional: open browser **Network** tab and show successful WebSocket to the Cloud Run URL.

---

## 5. Architecture diagram (for Devpost)

- Use the diagram from [../ARCHITECTURE.md](../ARCHITECTURE.md) (ASCII or redrawn).
- Export or save as image for submission.

**Asset:** Save as `docs/proof/architecture.png` for Devpost upload.

---

## Proof asset placeholders

| File | Description |
|------|-------------|
| `docs/proof/architecture.png` | Diagram for Devpost (export from ARCHITECTURE.md or redraw). |
| `docs/proof/cloudrun_logs.png` | Screenshot of Cloud Run Logs (or service details) during/after a live session. |

Add these files when producing the final proof pack; this folder tracks what to capture.
