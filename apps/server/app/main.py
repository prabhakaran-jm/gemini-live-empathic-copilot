"""
Empathic Co-Pilot backend – FastAPI app and WebSocket endpoint.
"""
from contextlib import asynccontextmanager
import json
import logging
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.websocket_handler import handle_websocket

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: e.g. init Gemini client pool if needed
    yield
    # Shutdown
    pass


app = FastAPI(title="Empathic Co-Pilot", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        await handle_websocket(websocket)
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
