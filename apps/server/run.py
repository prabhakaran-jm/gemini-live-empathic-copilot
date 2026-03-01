"""Run the backend. Usage: python run.py (local or Cloud Run). Uses PORT env when set."""
import logging
import os
import uvicorn

if __name__ == "__main__":
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO))
    port = int(os.environ.get("PORT", "8765"))
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)
