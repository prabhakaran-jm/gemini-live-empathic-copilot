"""Run the backend. Usage: python run.py (local or Cloud Run). Uses PORT env when set."""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)
