#!/usr/bin/env python3
"""
Smoke test: open a Gemini Live session, send a short PCM16 16kHz audio file chunk-by-chunk, print received events.
No UI. Requires GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_REGION (or GOOGLE_GENAI_API_KEY / GEMINI_API_KEY).

Run from repo root:
  cd apps/server && python -m scripts.smoke_test

Or from apps/server with venv activated:
  python scripts/smoke_test.py
"""
import asyncio
import base64
import os
import sys

# Allow importing app when run as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.gemini_live_client import (
    LiveSessionConfig,
    get_gemini_client,
)


def make_silent_pcm_chunks(num_chunks: int = 10, chunk_samples: int = 1600) -> list[bytes]:
    """PCM16 mono 16 kHz: each chunk = chunk_samples samples = chunk_samples*2 bytes."""
    chunk = b"\x00\x00" * chunk_samples  # 100 ms at 16 kHz
    return [chunk] * num_chunks


async def main() -> None:
    if not (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_GENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print("Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_REGION (or GOOGLE_GENAI_API_KEY / GEMINI_API_KEY) and re-run.")
        sys.exit(1)
    client = get_gemini_client()
    if client.__class__.__name__ == "StubGeminiLiveClient":
        print("Stub client returned (no credentials?). Set GOOGLE_CLOUD_PROJECT or API key.")
        sys.exit(1)
    config = LiveSessionConfig()
    print("Connecting to Gemini Live...")
    session = await client.connect(config)
    print("Connected. Sending 1s silent PCM in 100ms chunks, then waiting 3s for events...")
    chunks = make_silent_pcm_chunks(10)
    recv_task = asyncio.create_task(consume_events(session))
    for i, raw in enumerate(chunks):
        b64 = base64.b64encode(raw).decode("ascii")
        await session.send_audio(b64)
        await asyncio.sleep(0.05)
    await asyncio.sleep(3.0)
    await session.close()
    await asyncio.sleep(0.3)
    recv_task.cancel()
    try:
        await recv_task
    except asyncio.CancelledError:
        pass
    print("Done.")


async def consume_events(session) -> None:
    try:
        async for ev in session.recv_events():
            print(f"  event: {ev.kind!r} text={ev.text!r} message={ev.message!r}")
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
