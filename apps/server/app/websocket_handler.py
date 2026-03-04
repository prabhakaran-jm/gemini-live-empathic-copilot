"""
WebSocket handler: protocol (start/stop/audio), tension loop, coaching whispers.
Barge-in: when user sends audio while agent is generating, we stop generation (TODO in Gemini).
"""
import asyncio
import base64
import json
import logging
import os
import queue
import time
from collections import deque
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.coaching import COACHING_MOVES, generate_coaching
from app.gemini_live_client import (
    IGeminiLiveSession,
    LiveSessionConfig,
    generate_whisper_audio,
    get_gemini_client,
    transcribe_pcm16_audio,
)
from app.streaming_stt import start_streaming_stt_thread
from app.tension import AudioTelemetry, TensionState, compute_semantic_tension, compute_tension_loop

logger = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("MOCK", "").lower() in ("1", "true", "yes")
BARGE_IN_RMS_THRESHOLD = float(os.environ.get("BARGE_IN_RMS_THRESHOLD", "0.15"))
RMS_EMA_ALPHA = 0.2  # rms_ema = (1-alpha)*prev + alpha*current
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "0.02"))
WHISPER_COOLDOWN_SEC = 12.0
# Tension score at or above this triggers "tension_cross" whisper (env TENSION_WHISPER_THRESHOLD, default 20 for demo-friendly)
TENSION_WHISPER_THRESHOLD = int(os.environ.get("TENSION_WHISPER_THRESHOLD", "20"))
SILENCE_THRESHOLD_SEC = 2.5
TENSION_HIGH_WINDOW_SEC = 10.0
OVERLAP_WINDOW_SEC = 5.0
OVERLAP_MIN_COUNT = 2  # min "interrupted" events in last 5s for overlap heuristic
TELEMETRY_QUEUE_MAXSIZE = 32
TRANSCRIPT_CONTEXT_MAX_CHARS = 4000
ACTIVITY_START_RMS_THRESHOLD = float(os.environ.get("ACTIVITY_START_RMS_THRESHOLD", "0.01"))
TRANSCRIPT_FALLBACK_ENABLED = os.environ.get("TRANSCRIPT_FALLBACK_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
TRANSCRIPT_FALLBACK_POLL_SEC = float(os.environ.get("TRANSCRIPT_FALLBACK_POLL_SEC", "0.5"))
TRANSCRIPT_FALLBACK_END_SILENCE_SEC = float(
    os.environ.get("TRANSCRIPT_FALLBACK_END_SILENCE_SEC", "1.2")
)
TRANSCRIPT_FALLBACK_MIN_INTERVAL_SEC = float(
    os.environ.get("TRANSCRIPT_FALLBACK_MIN_INTERVAL_SEC", "10.0")
)
TRANSCRIPT_FALLBACK_MIN_VOICE_RMS = float(
    os.environ.get("TRANSCRIPT_FALLBACK_MIN_VOICE_RMS", "0.015")
)
TRANSCRIPT_FALLBACK_MIN_BYTES = int(
    os.environ.get("TRANSCRIPT_FALLBACK_MIN_BYTES", str(16000 * 2 * 2))
)  # ~2s PCM16 mono 16k
TRANSCRIPT_FALLBACK_MAX_BYTES = int(
    os.environ.get("TRANSCRIPT_FALLBACK_MAX_BYTES", str(16000 * 2 * 8))
)  # cap rolling buffer to ~8s
COACHING_LIVE_AUDIO = os.environ.get("COACHING_LIVE_AUDIO", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# When the Live session recv stream drops, attempt to reconnect and restart consume_recv_events (default 1).
GEMINI_RECONNECT = os.environ.get("GEMINI_RECONNECT", "1").strip().lower() in ("1", "true", "yes")
# Real-time transcription via Cloud Speech-to-Text streaming when Live does not emit transcript (default 1).
LIVE_STT_STREAMING = os.environ.get("LIVE_STT_STREAMING", "1").strip().lower() in ("1", "true", "yes")


async def send_json(ws: WebSocket, obj: dict[str, Any]) -> None:
    try:
        await ws.send_json(obj)
    except WebSocketDisconnect:
        # Client already closed the connection (e.g. after sending "stop"). Expected; no need to warn.
        msg_type = obj.get("type", "?")
        logger.debug("Send skipped (type=%s): client disconnected", msg_type)
    except Exception as e:
        msg_type = obj.get("type", "?")
        err_msg = str(e).strip() or getattr(e, "message", "") or type(e).__name__
        logger.warning(
            "Send failed (type=%s): %s: %s",
            msg_type,
            type(e).__name__,
            err_msg,
        )


async def handle_websocket(websocket: WebSocket) -> None:
    session: IGeminiLiveSession | None = None
    tension_state = TensionState()
    telemetry_queue: asyncio.Queue[AudioTelemetry | None] = asyncio.Queue(
        maxsize=TELEMETRY_QUEUE_MAXSIZE
    )
    tension_task: asyncio.Task | None = None
    agent_task: asyncio.Task | None = None
    events_task: asyncio.Task | None = None
    watch_task: asyncio.Task | None = None
    whisper_task: asyncio.Task | None = None
    fallback_transcript_task: asyncio.Task | None = None
    agent_output_started: bool = False
    degraded_mode: bool = False  # True when Gemini connect failed; tension + whisper_loop still run
    running = True
    rms_ema_ref: list[float] = [0.0]
    last_tension_score: int = 0
    prev_tension_score: int = 0
    tension_history: deque[tuple[float, int]] = deque()
    last_whisper_ts: float = 0.0
    interrupted_events: deque[float] = deque()
    transcript_context: str = ""
    latest_frame_base64: str | None = None  # optional webcam frame for vision-aware coaching
    last_voice_ts: float | None = None
    live_last_transcript_ts: float = 0.0
    fallback_last_emitted: str = ""
    fallback_audio_buffer = bytearray()
    fallback_has_voice: bool = False
    fallback_last_request_ts: float = 0.0
    live_audio_unavailable: bool = False
    stt_thread: Any = None
    stt_audio_queue: Any = None
    stt_result_queue: Any = None
    stt_reader_task: asyncio.Task | None = None
    stt_active: bool = False
    stt_permanently_failed: bool = False  # True after MAX consecutive failures; stops restart loop
    stt_consecutive_failures: int = 0
    STT_MAX_CONSECUTIVE_FAILURES: int = 3

    def on_tension(score: int) -> None:
        nonlocal last_tension_score, prev_tension_score, tension_history
        prev_tension_score = last_tension_score
        last_tension_score = score
        now = time.time()
        tension_history.append((now, score))
        while tension_history and now - tension_history[0][0] > TENSION_HIGH_WINDOW_SEC:
            tension_history.popleft()
        asyncio.create_task(
            send_json(websocket, {"type": "tension", "score": score, "ts": int(now * 1000)})
        )

    async def run_tension_loop() -> None:
        await compute_tension_loop(telemetry_queue, tension_state, on_tension, interval_sec=0.5)

    def enqueue_latest_telemetry(telemetry: AudioTelemetry) -> None:
        """
        Keep telemetry queue fresh and bounded by dropping stale items when full.
        compute_tension_loop only needs the newest sample per tick.
        """
        if telemetry_queue.full():
            try:
                telemetry_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            telemetry_queue.put_nowait(telemetry)
        except asyncio.QueueFull:
            # Best-effort freshness: if still full due race, drop this sample.
            pass

    def signal_tension_stop() -> None:
        """Insert stop sentinel without blocking, even if queue is currently full."""
        try:
            while True:
                telemetry_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            telemetry_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

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
        nonlocal session, agent_output_started, transcript_context, live_last_transcript_ts
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
                elif ev.kind in ("transcript_delta", "user_transcript_delta") and ev.text:
                    delta_text = ev.text if isinstance(ev.text, str) else str(ev.text)
                    # Keep rolling context for semantic scoring + coaching generation.
                    transcript_context = (transcript_context + delta_text)[-TRANSCRIPT_CONTEXT_MAX_CHARS:]
                    live_last_transcript_ts = time.time()
                    await send_json(
                        websocket,
                        {
                            "type": "transcript",
                            "delta": delta_text,
                            "full": transcript_context,
                            "ts": int(time.time() * 1000),
                        },
                    )
                elif ev.kind == "backchannel_audio" and ev.audio_base64:
                    # Suppress backchannel if a coaching whisper was sent recently (within 5s)
                    now = time.time()
                    if now - last_whisper_ts >= 5.0:
                        await send_json(
                            websocket,
                            {
                                "type": "backchannel_audio",
                                "audio_base64": ev.audio_base64,
                                "ts": int(now * 1000),
                            },
                        )
                elif ev.kind == "error":
                    await send_json(websocket, {"type": "error", "message": ev.message or ev.text})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("recv_events error: %s", e)

    async def watch_events_and_reconnect() -> None:
        """When consume_recv_events exits (Live stream died), try to reconnect and restart the recv loop."""
        nonlocal session, events_task, degraded_mode, last_voice_ts
        try:
            while running and session is not None and events_task is not None:
                try:
                    await events_task
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.warning("recv_events task exited: %s", e)
                if not running or session is None:
                    return
                old_session = session
                session = None
                last_voice_ts = None
                try:
                    await old_session.close()
                except Exception:
                    pass
                try:
                    client = get_gemini_client()
                    session = await client.connect(LiveSessionConfig())
                    events_task = asyncio.create_task(consume_recv_events())
                    await send_json(
                        websocket,
                        {"type": "event", "name": "reconnected", "ts": int(time.time() * 1000)},
                    )
                    logger.info("Gemini Live session reconnected")
                except Exception as e:
                    logger.warning("Gemini reconnect failed; staying in degraded mode: %s", e)
                    degraded_mode = True
                    session = None
                    return
        except asyncio.CancelledError:
            pass

    async def whisper_loop() -> None:
        """Real or degraded: every 250ms check deterministic rules; send whisper from coaching.py if cooldown passed."""
        nonlocal last_whisper_ts, prev_tension_score, last_tension_score, live_audio_unavailable
        while running and (session is not None or degraded_mode):
            await asyncio.sleep(0.25)
            now = time.time()
            if not running or (session is None and not degraded_mode):
                return
            if now - last_whisper_ts < WHISPER_COOLDOWN_SEC:
                continue
            trigger = None
            # (a) Tension crossed upward into >= threshold
            if prev_tension_score < TENSION_WHISPER_THRESHOLD and last_tension_score >= TENSION_WHISPER_THRESHOLD:
                trigger = "tension_cross"
            # (b) Overlap heuristic: high interruption rate in last 5s
            if trigger is None:
                recent = [t for t in interrupted_events if now - t <= OVERLAP_WINDOW_SEC]
                if len(recent) >= OVERLAP_MIN_COUNT:
                    trigger = "barge_in"
            # (c) Silence >2.5s and tension was >=70 in last 10s
            if trigger is None and tension_state.silence_start is not None:
                silence_sec = now - tension_state.silence_start
                if silence_sec >= SILENCE_THRESHOLD_SEC:
                    high_in_window = any(s >= 70 for _, s in tension_history if now - _ <= TENSION_HIGH_WINDOW_SEC)
                    if high_in_window:
                        trigger = "post_escalation_silence"
            if trigger is not None:
                last_whisper_ts = now
                prev_tension_score = last_tension_score
                # Reset tension state so tension can recover naturally after coaching
                tension_state.silence_start = None
                tension_state.overlap_timestamps.clear()
                coaching_result = await generate_coaching(
                    trigger=trigger,
                    tension_score=last_tension_score,
                    transcript_buffer=transcript_context,
                    image_base64=latest_frame_base64,
                )
                whisper_msg: dict[str, Any] = {
                    "type": "whisper",
                    "text": coaching_result["text"],
                    "move": coaching_result["move"],
                    "ts": int(now * 1000),
                }
                if COACHING_LIVE_AUDIO and not live_audio_unavailable:
                    try:
                        audio_b64 = await generate_whisper_audio(coaching_result["text"])
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning("generate_whisper_audio failed; disabling live whisper audio: %s", exc)
                        live_audio_unavailable = True
                        audio_b64 = None
                    if audio_b64:
                        whisper_msg["audio_base64"] = audio_b64
                await send_json(websocket, whisper_msg)

    async def fallback_transcript_loop() -> None:
        """
        Fallback transcript path:
        if Live doesn't emit transcript events, periodically transcribe buffered PCM via gemini-2.0-flash.
        """
        nonlocal transcript_context, live_last_transcript_ts, fallback_last_emitted, fallback_has_voice, fallback_last_request_ts

        async def emit_fallback_transcript(pcm: bytes) -> bool:
            nonlocal transcript_context, live_last_transcript_ts, fallback_last_emitted
            text = await transcribe_pcm16_audio(pcm, sample_rate_hz=16000)
            if not text:
                return False
            normalized = " ".join(text.split())
            if not normalized:
                return False
            if normalized == fallback_last_emitted:
                return False
            fallback_last_emitted = normalized
            delta_text = normalized + " "
            transcript_context = (transcript_context + delta_text)[-TRANSCRIPT_CONTEXT_MAX_CHARS:]
            live_last_transcript_ts = time.time()
            logger.info("Fallback transcript emitted: %s", normalized[:120])
            await send_json(
                websocket,
                {
                    "type": "transcript",
                    "delta": delta_text,
                    "full": transcript_context,
                    "ts": int(time.time() * 1000),
                },
            )
            return True

        while running and (session is not None or degraded_mode):
            await asyncio.sleep(TRANSCRIPT_FALLBACK_POLL_SEC)
            if not running:
                return
            if not TRANSCRIPT_FALLBACK_ENABLED:
                continue
            # If Live transcript is active recently, fallback stays idle.
            now = time.time()
            if live_last_transcript_ts and (now - live_last_transcript_ts) < 6.0:
                fallback_audio_buffer.clear()
                fallback_has_voice = False
                continue
            if len(fallback_audio_buffer) < TRANSCRIPT_FALLBACK_MIN_BYTES:
                continue
            if not fallback_has_voice:
                # Avoid transcribing sustained silence.
                fallback_audio_buffer.clear()
                continue
            silence_elapsed = (
                last_voice_ts is None or (now - last_voice_ts) >= TRANSCRIPT_FALLBACK_END_SILENCE_SEC
            )
            buffer_full = len(fallback_audio_buffer) >= TRANSCRIPT_FALLBACK_MAX_BYTES
            if not (silence_elapsed or buffer_full):
                continue
            if now - fallback_last_request_ts < TRANSCRIPT_FALLBACK_MIN_INTERVAL_SEC:
                continue
            fallback_last_request_ts = now
            pcm = bytes(fallback_audio_buffer)
            fallback_audio_buffer.clear()
            fallback_has_voice = False
            await emit_fallback_transcript(pcm)

    async def stt_result_reader_loop() -> None:
        """Read streaming STT results and send transcript messages; update transcript_context."""
        nonlocal transcript_context, live_last_transcript_ts, stt_active, stt_audio_queue, stt_result_queue
        nonlocal stt_consecutive_failures, stt_permanently_failed
        if stt_result_queue is None:
            return
        loop = asyncio.get_event_loop()
        _got_any_transcript = False
        _start_ts = time.time()

        def get_result() -> tuple[str | None, bool] | None:
            try:
                return stt_result_queue.get(timeout=0.25)
            except queue.Empty:
                return None

        try:
            while running and stt_result_queue is not None:
                item = await loop.run_in_executor(None, get_result)
                if item is None:
                    continue
                transcript, is_final = item
                if transcript is None:
                    break
                _got_any_transcript = True
                t = transcript.strip()
                if not t:
                    continue
                transcript_context = (transcript_context + " " + t).strip()[-TRANSCRIPT_CONTEXT_MAX_CHARS:]
                live_last_transcript_ts = time.time()
                delta_text = t + (" " if is_final else "")
                await send_json(
                    websocket,
                    {
                        "type": "transcript",
                        "delta": delta_text,
                        "full": transcript_context,
                        "ts": int(time.time() * 1000),
                    },
                )
        finally:
            elapsed = time.time() - _start_ts
            if _got_any_transcript:
                stt_consecutive_failures = 0
            elif elapsed < 5.0:
                # Exited quickly with no transcripts — likely a crash / API error.
                stt_consecutive_failures += 1
                if stt_consecutive_failures >= STT_MAX_CONSECUTIVE_FAILURES:
                    stt_permanently_failed = True
                    logger.warning(
                        "Streaming STT failed %d times in a row; disabling. Falling back to batch.",
                        stt_consecutive_failures,
                    )
            logger.info(
                "Streaming STT reader loop exited (got_transcript=%s, elapsed=%.1fs, failures=%d); falling back to batch if enabled",
                _got_any_transcript, elapsed, stt_consecutive_failures,
            )
            stt_active = False
            stt_audio_queue = None
            stt_result_queue = None

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
                if session is not None or tension_task is not None:
                    await send_json(websocket, {"type": "error", "message": "Already started"})
                    continue
                # Optional: initial webcam frame for vision-aware coaching
                config = msg.get("config") or {}
                if isinstance(config, dict):
                    img = (config.get("image") or "").strip()
                    latest_frame_base64 = img if img else None
                await send_json(websocket, {"type": "ready"})
                last_voice_ts = None
                live_last_transcript_ts = 0.0
                fallback_last_emitted = ""
                fallback_last_request_ts = 0.0
                fallback_audio_buffer.clear()
                fallback_has_voice = False
                live_audio_unavailable = False
                if not MOCK_MODE:
                    try:
                        client = get_gemini_client()
                        session = await client.connect(LiveSessionConfig())
                        if hasattr(session, "recv_events"):
                            events_task = asyncio.create_task(consume_recv_events())
                            if GEMINI_RECONNECT:
                                watch_task = asyncio.create_task(watch_events_and_reconnect())
                        if hasattr(session, "agent_turns"):
                            agent_task = asyncio.create_task(consume_agent_turns())
                        whisper_task = asyncio.create_task(whisper_loop())
                        # Streaming STT started lazily on first audio to avoid "400 Audio Timeout: send close to real time".
                        if TRANSCRIPT_FALLBACK_ENABLED and stt_audio_queue is None:
                            fallback_transcript_task = asyncio.create_task(fallback_transcript_loop())
                    except Exception as e:
                        logger.exception("Gemini connect failed; starting degraded (local-only) mode: %s", e)
                        await send_json(
                            websocket,
                            {"type": "error", "message": "Gemini unavailable; running local coaching only"},
                        )
                        session = None
                        degraded_mode = True
                        whisper_task = asyncio.create_task(whisper_loop())
                        if TRANSCRIPT_FALLBACK_ENABLED and stt_audio_queue is None:
                            fallback_transcript_task = asyncio.create_task(fallback_transcript_loop())
                tension_task = asyncio.create_task(run_tension_loop())
                if MOCK_MODE:
                    mock_task = asyncio.create_task(mock_loop())
            elif t == "stop":
                # Flush any pending fallback speech buffer before shutdown.
                if (
                    TRANSCRIPT_FALLBACK_ENABLED
                    and fallback_has_voice
                    and len(fallback_audio_buffer) >= TRANSCRIPT_FALLBACK_MIN_BYTES
                ):
                    pcm = bytes(fallback_audio_buffer)
                    fallback_audio_buffer.clear()
                    fallback_has_voice = False
                    text = await transcribe_pcm16_audio(pcm, sample_rate_hz=16000)
                    if text:
                        normalized = " ".join(text.split())
                        if normalized and normalized != fallback_last_emitted:
                            fallback_last_emitted = normalized
                            delta_text = normalized + " "
                            transcript_context = (transcript_context + delta_text)[-TRANSCRIPT_CONTEXT_MAX_CHARS:]
                            live_last_transcript_ts = time.time()
                            await send_json(
                                websocket,
                                {
                                    "type": "transcript",
                                    "delta": delta_text,
                                    "full": transcript_context,
                                    "ts": int(time.time() * 1000),
                                },
                            )
                running = False
                if stt_audio_queue is not None:
                    try:
                        stt_audio_queue.put(None, block=False)
                    except queue.Full:
                        pass
                if tension_task:
                    signal_tension_stop()
                    tension_task.cancel()
                    try:
                        await tension_task
                    except asyncio.CancelledError:
                        pass
                if session:
                    await session.close()
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
                if watch_task:
                    watch_task.cancel()
                    try:
                        await watch_task
                    except asyncio.CancelledError:
                        pass
                if whisper_task:
                    whisper_task.cancel()
                    try:
                        await whisper_task
                    except asyncio.CancelledError:
                        pass
                if fallback_transcript_task:
                    fallback_transcript_task.cancel()
                    try:
                        await fallback_transcript_task
                    except asyncio.CancelledError:
                        pass
                if stt_reader_task and not stt_reader_task.done():
                    stt_reader_task.cancel()
                    try:
                        await stt_reader_task
                    except asyncio.CancelledError:
                        pass
                if stt_thread is not None and stt_thread.is_alive():
                    stt_thread.join(timeout=2.0)
                if mock_task:
                    mock_task.cancel()
                    try:
                        await mock_task
                    except asyncio.CancelledError:
                        pass
                await send_json(websocket, {"type": "stopped"})
                break
            elif t == "frame":
                # Optional: update webcam frame for vision-aware coaching (base64 JPEG)
                b64 = (msg.get("base64") or msg.get("image") or "").strip()
                latest_frame_base64 = b64 if b64 else latest_frame_base64
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
                now_ts = time.time()
                # Start streaming STT on first audio chunk so the stream gets data immediately (avoids 400 Audio Timeout).
                if LIVE_STT_STREAMING and stt_audio_queue is None and not stt_active and not stt_permanently_failed:
                    stt_ctx = start_streaming_stt_thread(sample_rate_hz=16000, language_code="en-US")
                    if stt_ctx is not None:
                        stt_active = True
                        stt_thread, stt_audio_queue, stt_result_queue = stt_ctx
                        stt_reader_task = asyncio.create_task(stt_result_reader_loop())
                        logger.info("Streaming Speech-to-Text started on first audio")
                if stt_audio_queue is not None:
                    try:
                        stt_audio_queue.put(raw_bytes, block=False)
                    except queue.Full:
                        pass
                if TRANSCRIPT_FALLBACK_ENABLED and stt_audio_queue is None:
                    if rms_raw >= TRANSCRIPT_FALLBACK_MIN_VOICE_RMS:
                        fallback_has_voice = True
                    # Keep fallback buffer focused on likely speech segments to improve ASR quality.
                    keep_for_fallback = fallback_has_voice or (
                        rms_raw >= (TRANSCRIPT_FALLBACK_MIN_VOICE_RMS * 0.6)
                    )
                    if keep_for_fallback:
                        fallback_audio_buffer.extend(raw_bytes)
                        if len(fallback_audio_buffer) > TRANSCRIPT_FALLBACK_MAX_BYTES:
                            del fallback_audio_buffer[:-TRANSCRIPT_FALLBACK_MAX_BYTES]
                telemetry = AudioTelemetry(
                    rms=rms_ema,
                    is_silence=is_silence,
                    is_overlap=barge_in_trigger,
                    ts=now_ts,
                    semantic_score=compute_semantic_tension(transcript_context),
                )
                enqueue_latest_telemetry(telemetry)
                if session and not MOCK_MODE:
                    # Track voice timestamps for fallback transcript timing
                    if rms_ema >= ACTIVITY_START_RMS_THRESHOLD:
                        last_voice_ts = now_ts
                    if barge_in_trigger:
                        if hasattr(session, "stop_generation"):
                            await session.stop_generation()
                        interrupted_events.append(now_ts)
                        while interrupted_events and now_ts - interrupted_events[0] > OVERLAP_WINDOW_SEC:
                            interrupted_events.popleft()
                        await send_json(
                            websocket,
                            {"type": "event", "name": "interrupted", "ts": int(now_ts * 1000)},
                        )
                        agent_output_started = False
                    # Always send audio to Gemini Live — auto VAD handles
                    # speech detection. Do NOT send manual activity_start/end
                    # or audio_stream_end; they conflict with auto VAD and
                    # cause the session to return 0 messages.
                    await session.send_audio(base64_audio)
            else:
                await send_json(websocket, {"type": "error", "message": f"Unknown type: {t}"})

    finally:
        if session:
            try:
                await session.close()
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
        if watch_task and not watch_task.done():
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass
        if whisper_task and not whisper_task.done():
            whisper_task.cancel()
            try:
                await whisper_task
            except asyncio.CancelledError:
                pass
        if fallback_transcript_task and not fallback_transcript_task.done():
            fallback_transcript_task.cancel()
            try:
                await fallback_transcript_task
            except asyncio.CancelledError:
                pass
        if mock_task and not mock_task.done():
            mock_task.cancel()
            try:
                await mock_task
            except asyncio.CancelledError:
                pass
