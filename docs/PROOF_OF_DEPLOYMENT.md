# Proof of deployment – checklist for judges

Use this checklist when recording a **proof video** that the Empathic Co-Pilot backend is deployed and working on **Google Cloud Run**.

## Checklist (show in the video)

- [ ] **1. Cloud Run service details**
  - Open **Google Cloud Console** → **Cloud Run**.
  - Select the deployed service (e.g. `empathic-copilot`).
  - Show the **Service details** (URL, region, image, env vars if visible).
  - Confirm the service is in a **Serving** state.

- [ ] **2. Cloud Run logs with an active session**
  - In the same Cloud Run service, open the **Logs** tab.
  - Start a session from the Empathic Co-Pilot UI (connect to the Cloud Run WebSocket URL).
  - Show log entries while the session is active (e.g. WebSocket connections, health checks, or application logs).

- [ ] **3. Health endpoint returns 200**
  - In a browser or with `curl`, open:
    `https://YOUR_CLOUD_RUN_URL/health`
  - Show that the response is HTTP **200** and body is `{"status":"ok"}` (or equivalent).

- [ ] **4. UI connecting to the Cloud Run WebSocket**
  - Open the Empathic Co-Pilot **frontend** (local or hosted) configured to use the Cloud Run backend:
    - Either set `VITE_WS_URL=wss://YOUR_CLOUD_RUN_URL/ws` and run the app, or use a pre-built app that points to this URL.
  - Click **Start session** and show that:
    - The UI shows **ready** / session active (e.g. tension bar, optional transcript).
    - The **Event log** shows incoming messages (e.g. `ready`, `tension`, or `whisper`).
  - Optional: briefly show the browser **Network** tab with a successful WebSocket connection to the Cloud Run URL.

## Suggested video flow

1. Show Cloud Run service in the console (name, URL, status).
2. Show `/health` returning 200 in browser or terminal.
3. Open the app UI; set or show that the backend URL is the Cloud Run URL.
4. Start session; show Event log and any live UI (tension, transcript).
5. Switch to Cloud Run Logs and show entries while the session is active.
6. (Optional) Stop session and show a final log line or health check again.

## Notes for judges

- The **backend** is the FastAPI app in `apps/server`, deployed as a single container to Cloud Run.
- The **frontend** can run locally (e.g. `npm run dev` in `apps/web`) with `VITE_WS_URL=wss://...` set to the Cloud Run URL; no need to host the frontend on GCP for this proof.
- **WebSocket** is used end-to-end (no SSE); the deploy is configured with a long request timeout and min-instances for demo stability.
