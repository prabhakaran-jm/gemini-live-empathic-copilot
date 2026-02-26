"""
Deterministic tension score (0–100) from audio telemetry.
Inputs: RMS volume, silence >2.5s, overlap (VAD/talk spurts).
MVP: stub that returns a value from recent telemetry; real logic TODO.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

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
    recent_rms: list[float] = field(default_factory=list)
    max_rms_history: int = 30


def compute_tension_from_telemetry(telemetry: AudioTelemetry, state: TensionState) -> int:
    """
    Compute tension score 0–100 from current telemetry and state.
    Deterministic: same inputs -> same score.
    """
    # Update state
    if telemetry.is_silence:
        if state.silence_start is None:
            state.silence_start = telemetry.ts
    else:
        state.silence_start = None
        state.recent_rms.append(telemetry.rms)
        if len(state.recent_rms) > state.max_rms_history:
            state.recent_rms.pop(0)
    if telemetry.is_overlap:
        state.overlap_count += 1
    state.last_rms = telemetry.rms

    # Score components (each 0..1 scale, then weighted)
    # 1) Volume: higher RMS -> higher tension
    rms_score = min(1.0, state.last_rms * 1.5) if state.recent_rms else 0.0

    # 2) Long silence: tension increases after >2.5s silence (awkwardness)
    silence_sec = (telemetry.ts - state.silence_start) if state.silence_start else 0.0
    silence_score = min(1.0, silence_sec / state.silence_threshold_sec) if telemetry.is_silence else 0.0

    # 3) Overlap: more overlaps -> higher tension (turn-taking friction)
    overlap_score = min(1.0, state.overlap_count * 0.2)

    # Combined: weighted average, then 0–100
    combined = 0.5 * rms_score + 0.3 * silence_score + 0.2 * overlap_score
    return int(min(100, max(0, combined * 100)))


async def compute_tension_loop(
    telemetry_queue: asyncio.Queue[AudioTelemetry | None],
    state: TensionState,
    on_tension: Callable[[int], None],
    interval_sec: float = 0.5,
) -> None:
    """
    Loop: every interval_sec, take latest telemetry (or use last), compute tension, call on_tension(score).
    Stops when None is put in telemetry_queue.
    """
    last_telemetry: AudioTelemetry | None = None
    try:
        while True:
            try:
                t = telemetry_queue.get_nowait()
                if t is None:
                    return
                last_telemetry = t
            except asyncio.QueueEmpty:
                pass
            if last_telemetry is not None:
                score = compute_tension_from_telemetry(last_telemetry, state)
                on_tension(score)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        pass
