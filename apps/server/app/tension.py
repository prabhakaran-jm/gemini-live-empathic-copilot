"""
Deterministic tension score (0–100) from audio telemetry.
Inputs: RMS volume, silence >2.5s, overlap (VAD/talk spurts).
Deterministic tension scoring from RMS, silence duration, and overlap signals (0-100).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

SPEECH_RMS_FLOOR = 0.01  # RMS below this is considered silence/noise, not speech

# --- Telemetry (to be filled by audio pipeline) ---


@dataclass
class AudioTelemetry:
    """Per-chunk or aggregated telemetry for tension computation."""
    rms: float = 0.0          # 0..1 normalized
    is_silence: bool = False  # chunk below threshold
    is_overlap: bool = False  # user spoke while agent was generating (barge-in)
    ts: float = 0.0           # Unix time


@dataclass
class TensionState:
    """Mutable state for deterministic tension over a session."""
    last_rms: float = 0.0
    silence_start: float | None = None  # time when current silence started
    silence_threshold_sec: float = 2.5
    overlap_count: int = 0
    overlap_timestamps: list[float] = field(default_factory=list)
    overlap_window_sec: float = 10.0
    recent_rms: list[float] = field(default_factory=list)
    max_rms_history: int = 50  # ~2 seconds at 25 chunks/sec


def compute_tension_from_telemetry(telemetry: AudioTelemetry, state: TensionState) -> int:
    """
    Compute tension score 0–100 from current telemetry and state.
    Deterministic: same inputs -> same score.
    """
    # Update state — ALWAYS append RMS so avg_rms decays during silence
    if telemetry.is_silence:
        if state.silence_start is None:
            state.silence_start = telemetry.ts
    else:
        state.silence_start = None
    # Always track RMS (including silence) so the sliding window reflects actual audio levels.
    # Without this, silence leaves old speech values in recent_rms and tension never decays.
    state.recent_rms.append(telemetry.rms)
    if len(state.recent_rms) > state.max_rms_history:
        state.recent_rms.pop(0)
    if telemetry.is_overlap:
        state.overlap_timestamps.append(telemetry.ts)
    # Keep only recent overlap events so interruption influence naturally decays.
    cutoff = telemetry.ts - state.overlap_window_sec
    while state.overlap_timestamps and state.overlap_timestamps[0] < cutoff:
        state.overlap_timestamps.pop(0)
    state.overlap_count = len(state.overlap_timestamps)
    state.last_rms = telemetry.rms

    # Score components (each 0..1 scale, then weighted)
    # 1) Volume: higher RMS -> higher tension (use recent average for stability)
    avg_rms = sum(state.recent_rms) / len(state.recent_rms) if state.recent_rms else 0.0
    # Scale tuned for real-world EMA'd RMS: calm(0.02)→0.2, normal(0.04)→0.4, raised(0.06)→0.6, loud(0.08+)→0.8
    rms_score = min(1.0, max(0.0, avg_rms * 10.0))

    # 2) Long silence: tension increases after >2.5s silence (awkwardness)
    # But only contributes meaningfully if there was prior speech activity
    silence_sec = (telemetry.ts - state.silence_start) if state.silence_start else 0.0
    silence_score = min(1.0, silence_sec / state.silence_threshold_sec) if telemetry.is_silence else 0.0
    # Dampen silence score if no real speech has occurred (avoid false tension on startup)
    speech_entries = sum(1 for r in state.recent_rms if r > SPEECH_RMS_FLOOR)
    if speech_entries < 5:
        silence_score *= 0.2

    # 3) Overlap: more overlaps -> higher tension (turn-taking friction)
    overlap_score = min(1.0, state.overlap_count * 0.2)

    # Combined: weighted average, then 0–100
    # Volume is primary signal; silence and overlap are secondary
    combined = 0.55 * rms_score + 0.25 * silence_score + 0.20 * overlap_score
    return int(min(100, max(0, combined * 100)))


async def compute_tension_loop(
    telemetry_queue: asyncio.Queue[AudioTelemetry | None],
    state: TensionState,
    on_tension: Callable[[int], None],
    interval_sec: float = 0.5,
) -> None:
    """
    Loop: every interval_sec, drain ALL queued telemetry to update state, then emit score.
    Audio chunks arrive at ~25/sec but this loop runs at 2/sec; we must process ALL
    queued items so that recent_rms history builds up properly.
    Stops when None is put in telemetry_queue.
    """
    try:
        while True:
            # Drain ALL queued telemetry — each item updates state (recent_rms, silence, overlap)
            score = None
            while True:
                try:
                    t = telemetry_queue.get_nowait()
                    if t is None:
                        return
                    score = compute_tension_from_telemetry(t, state)
                except asyncio.QueueEmpty:
                    break
            if score is not None:
                on_tension(score)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        pass
