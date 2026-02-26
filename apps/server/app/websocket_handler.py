"""
WebSocket handler: protocol (start/stop/audio), tension loop, coaching whispers.
Barge-in: when user sends audio while agent is generating, we stop generation (TODO in Gemini).
"""
import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from fastapi import WebSocket

from app.coaching import COACHING_MOVES, get_move_by_id
from app.gemini_live_client import (
    AgentTurn,
    IGeminiLiveSession,
    LiveSessionConfig,
    get_gemini_client,
)
from app.tension import AudioTelemetry, TensionState, compute_tension_loop

logger = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("MOCK", "").lower() in ("1", "true", "yes")
BARGE_IN_RMS_THRESHOLD = float(os.environ.get("BARGE_IN_RMS_THRESHOLD", "0.15"))
RMS_EMA_ALPHA = 0.2  # rms_ema = (1-alpha)*prev + alpha*current
SILENCE_RMS_THRESHOLD = 0.05
WHISPER_COOLDOWN_SEC = 12.0
SILENCE_THRESHOLD_SEC = 2.5
TENSION_HIGH_WINDOW_SEC = 10.0
OVERLAP_WINDOW_SEC = 5.0
OVERLAP_MIN_COUNT = 2  # min "interrupted" events in last 5s for overlap heuristic


async def send_json(ws: WebSocket, obj: dict[str, Any]) -> None:
    try:
        await ws.send_json(obj)
    except Exception as e:
        logger.warning("Send failed: %s", e)


async def handle_websocket(websocket: WebSocket) -> None:
    session: IGeminiLiveSession | None = None
    tension_state = TensionState()
    telemetry_queue: asyncio.Queue[AudioTelemetry | None] = asyncio.Queue()
    tension_task: asyncio.Task | None = None
    agent_task: asyncio.Task | None = None
    events_task: asyncio.Task | None = None
    whisper_task: asyncio.Task | None = None
    agent_output_started: bool = False
    running = True
    rms_ema_ref: list[float] = [0.0]
    last_tension_score: int = 0
    prev_tension_score: int = 0
    tension_history: list[tuple[float, int]] = []
    last_whisper_ts: float = 0.0
    interrupted_events: list[float] = []

    def on_tension(score: int) -> None:
        nonlocal last_tension_score, prev_tension_score, tension_history
        prev_tension_score = last_tension_score
        last_tension_score = score
        now = time.time()
        tension_history.append((now, score))
        while tension_history and now - tension_history[0][0] > TENSION_HIGH_WINDOW_SEC:
            tension_history.pop(0)
        asyncio.create_task(
            send_json(websocket, {"type": "tension", "score": score, "ts": int(now * 1000)})
        )

    async def run_tension_loop() -> None:
        await compute_tension_loop(telemetry_queue, tension_state, on_tension, interval_sec=0.5)

    async def consume_agent_turns() -> None:
        """Stub only: forward injected turns as whispers (coaching still from coaching.py)."""
        nonlocal session
        if session is None:
            return
        if not hasattr(session, "agent_turns"):
            return
        try:
            async for turn in session.agent_turns():
                if not running:
                    return
                if turn.text:
                    await send_json(
                        websocket,
                        {
                            "type": "whisper",
                            "text": turn.text,
                            "move": getattr(turn, "move", ""),
                            "ts": int(time.time() * 1000),
                        },
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Agent turn consumer error: %s", e)

    async def consume_recv_events() -> None:
        """Real client: consume recv_events; track agent_output_started/stopped; emit transcript_delta (optional), error, and interrupted on barge-in."""
        nonlocal session, agent_output_started
        if session is None or not hasattr(session, "recv_events"):
            return
        try:
            async for ev in session.recv_events():
                if not running:
                    return
                if ev.kind == "agent_output_started":
                    agent_output_started = True
                elif ev.kind == "agent_output_stopped":
                    agent_output_started = False
                elif ev.kind == "transcript_delta" and ev.text:
                    await send_json(
                        websocket,
                        {"type": "transcript", "delta": ev.text, "ts": int(time.time() * 1000)},
                    )
                elif ev.kind == "error":
                    await send_json(websocket, {"type": "error", "message": ev.message or ev.text})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("recv_events error: %s", e)

    async def whisper_loop() -> None:
        """Real mode only: every 250ms check deterministic rules; send whisper from coaching.py if cooldown passed."""
        nonlocal last_whisper_ts, prev_tension_score, last_tension_score
        while running and session is not None:
            await asyncio.sleep(0.25)
            if not running or session is None:
                return
            now = time.time()
            if now - last_whisper_ts < WHISPER_COOLDOWN_SEC:
                continue
            move_entry = None
            # (a) Tension crossed upward into >=40
            if prev_tension_score < 40 and last_tension_score >= 40:
                move_entry = get_move_by_id("slow_down")
            # (b) Overlap heuristic: high interruption rate in last 5s
            if move_entry is None:
                recent = [t for t in interrupted_events if now - t <= OVERLAP_WINDOW_SEC]
                if len(recent) >= OVERLAP_MIN_COUNT:
                    move_entry = get_move_by_id("reflect_back")
            # (c) Silence >2.5s and tension was >=70 in last 10s
            if move_entry is None and tension_state.silence_start is not None:
                silence_sec = now - tension_state.silence_start
                if silence_sec >= SILENCE_THRESHOLD_SEC:
                    high_in_window = any(s >= 70 for _, s in tension_history if now - _ <= TENSION_HIGH_WINDOW_SEC)
                    if high_in_window:
                        move_entry = get_move_by_id("clarify_intent")
            if move_entry is not None:
                last_whisper_ts = now
                prev_tension_score = last_tension_score
                await send_json(
                    websocket,
                    {"type": "whisper", "text": move_entry["text"], "move": move_entry["move"], "ts": int(now * 1000)},
                )

    async def mock_loop() -> None:
        """When MOCK_MODE: periodically send tension + occasional whisper."""
        import random
        idx = 0
        while running:
            await asyncio.sleep(2.0)
            if not running:
                return
            score = random.randint(20, 70)
            await send_json(websocket, {"type": "tension", "score": score, "ts": int(time.time() * 1000)})
            idx += 1
            if idx % 3 == 0 and COACHING_MOVES:
                move = random.choice(COACHING_MOVES)
                await send_json(
                    websocket,
                    {"type": "whisper", "text": move["text"], "move": move["move"], "ts": int(time.time() * 1000)},
                )

    mock_task: asyncio.Task | None = None
    try:
        while running:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_json(websocket, {"type": "error", "message": "Invalid JSON"})
                continue
            t = msg.get("type")
            if t == "start":
                if session is not None:
                    await send_json(websocket, {"type": "error", "message": "Already started"})
                    continue
                await send_json(websocket, {"type": "ready"})
                if not MOCK_MODE:
                    client = get_gemini_client()
                    session = await client.connect(LiveSessionConfig())
                    if hasattr(session, "recv_events"):
                        events_task = asyncio.create_task(consume_recv_events())
                    if hasattr(session, "agent_turns"):
                        agent_task = asyncio.create_task(consume_agent_turns())
                    whisper_task = asyncio.create_task(whisper_loop())
                tension_task = asyncio.create_task(run_tension_loop())
                if MOCK_MODE:
                    mock_task = asyncio.create_task(mock_loop())
            elif t == "stop":
                running = False
                if tension_task:
                    await telemetry_queue.put(None)
                    tension_task.cancel()
                    try:
                        await tension_task
                    except asyncio.CancelledError:
                        pass
                if session:
                    await session.disconnect()
                    session = None
                if agent_task:
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass
                if events_task:
                    events_task.cancel()
                    try:
                        await events_task
                    except asyncio.CancelledError:
                        pass
                if whisper_task:
                    whisper_task.cancel()
                    try:
                        await whisper_task
                    except asyncio.CancelledError:
                        pass
                if mock_task:
                    mock_task.cancel()
                    try:
                        await mock_task
                    except asyncio.CancelledError:
                        pass
                await send_json(websocket, {"type": "stopped"})
                break
            elif t == "audio":
                base64_audio = (msg.get("base64") or "").strip()
                if not base64_audio:
                    base64_audio = (msg.get("pcm_base64") or "").strip()
                    if base64_audio:
                        logger.warning("pcm_base64 is deprecated; use 'base64' per protocol.")
                if not base64_audio:
                    continue
                try:
                    raw_bytes = base64.b64decode(base64_audio, validate=True)
                except Exception:
                    continue
                telemetry_in = msg.get("telemetry") or {}
                rms_raw = telemetry_in.get("rms") if isinstance(telemetry_in.get("rms"), (int, float)) else None
                if rms_raw is None:
                    rms_raw = min(1.0, len(raw_bytes) / 1024.0) if raw_bytes else 0.0
                else:
                    rms_raw = min(1.0, max(0.0, float(rms_raw)))
                rms_ema_ref[0] = (1.0 - RMS_EMA_ALPHA) * rms_ema_ref[0] + RMS_EMA_ALPHA * rms_raw
                rms_ema = rms_ema_ref[0]
                is_silence = rms_ema < SILENCE_RMS_THRESHOLD
                barge_in_trigger = agent_output_started and rms_ema >= BARGE_IN_RMS_THRESHOLD
                telemetry = AudioTelemetry(
                    rms=rms_ema,
                    is_silence=is_silence,
                    is_overlap=barge_in_trigger,
                    ts=time.time(),
                )
                try:
                    telemetry_queue.put_nowait(telemetry)
                except asyncio.QueueFull:
                    pass
                if session and not MOCK_MODE:
                    if barge_in_trigger:
                        if hasattr(session, "stop_generation"):
                            await session.stop_generation()
                        now_ts = time.time()
                        interrupted_events.append(now_ts)
                        while interrupted_events and now_ts - interrupted_events[0] > OVERLAP_WINDOW_SEC:
                            interrupted_events.pop(0)
                        await send_json(
                            websocket,
                            {"type": "event", "name": "interrupted", "ts": int(now_ts * 1000)},
                        )
                        agent_output_started = False
                    await session.send_audio(base64_audio)
            else:
                await send_json(websocket, {"type": "error", "message": f"Unknown type: {t}"})

    finally:
        if session:
            try:
                await session.disconnect()
            except Exception:
                pass
        if tension_task and not tension_task.done():
            tension_task.cancel()
            try:
                await tension_task
            except asyncio.CancelledError:
                pass
        if events_task and not events_task.done():
            events_task.cancel()
            try:
                await events_task
            except asyncio.CancelledError:
                pass
        if whisper_task and not whisper_task.done():
            whisper_task.cancel()
            try:
                await whisper_task
            except asyncio.CancelledError:
                pass
        if mock_task and not mock_task.done():
            mock_task.cancel()
            try:
                await mock_task
            except asyncio.CancelledError:
                pass
