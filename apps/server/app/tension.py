"""
Deterministic tension score (0–100) from audio telemetry + transcript content.
Inputs: RMS volume, silence >2.5s, overlap (barge-in / interruption count), semantic escalation markers.
Four-signal formula: ~40% RMS, ~25% silence duration, ~15% overlap, ~20% semantic.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

# Escalation markers for semantic tension signal.
# Presence of these in recent transcript increases tension.
# Categories: absolutes, blame/accusation, dismissal, hostility, frustration.
ESCALATION_MARKERS: list[str] = [
    # Absolutes
    "always", "never", "every time", "nothing ever",
    # Blame / accusation
    "your fault", "you always", "you never", "because of you",
    "you don't care", "you don't listen",
    # Dismissal
    "whatever", "fine then", "forget it", "i don't care",
    "doesn't matter", "pointless",
    # Hostility / contempt
    "stupid", "ridiculous", "pathetic", "shut up",
    "hate", "can't stand", "sick of",
    # Frustration
    "i can't believe", "are you serious", "how dare you",
    "unbelievable", "this is insane",
]


def compute_semantic_tension(transcript_tail: str | None) -> float:
    """
    Compute semantic tension (0.0–1.0) from recent transcript text.
    Counts distinct escalation markers found; each hit adds 0.25, capped at 1.0.
    Case-insensitive matching on the last ~200 chars.
    """
    if not transcript_tail:
        return 0.0
    text_lower = transcript_tail[-200:].lower()
    hits = sum(1 for marker in ESCALATION_MARKERS if marker in text_lower)
    return min(1.0, hits * 0.25)


# --- Telemetry (to be filled by audio pipeline) ---


@dataclass
class AudioTelemetry:
    """Per-chunk or aggregated telemetry for tension computation."""
    rms: float = 0.0          # 0..1 normalized
    is_silence: bool = False  # chunk below threshold
    is_overlap: bool = False  # user spoke while agent was generating (barge-in)
    ts: float = 0.0           # Unix time
    semantic_score: float = 0.0  # 0.0–1.0 from transcript content analysis


@dataclass
class TensionState:
    """Mutable state for deterministic tension over a session."""
    last_rms: float = 0.0
    silence_start: float | None = None  # time when current silence started
    silence_threshold_sec: float = 2.5
    overlap_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=20))  # recent barge-in times for decay
    recent_rms: deque[float] = field(default_factory=lambda: deque(maxlen=30))
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
    if telemetry.is_overlap:
        state.overlap_timestamps.append(telemetry.ts)
    # Only count overlaps in the last 10 seconds (time-based decay)
    while state.overlap_timestamps and telemetry.ts - state.overlap_timestamps[0] > 10.0:
        state.overlap_timestamps.popleft()
    state.last_rms = telemetry.rms

    # Score components (each 0..1 scale, then weighted)
    # 1) Volume: higher RMS -> higher tension
    rms_score = min(1.0, state.last_rms * 1.5) if state.recent_rms else 0.0

    # 2) Long silence: tension increases after >2.5s silence (awkwardness)
    silence_sec = (telemetry.ts - state.silence_start) if state.silence_start else 0.0
    silence_score = min(1.0, silence_sec / state.silence_threshold_sec) if telemetry.is_silence else 0.0

    # 3) Overlap: recent barge-ins only (decays after 10s)
    overlap_score = min(1.0, len(state.overlap_timestamps) * 0.2)

    # 4-signal: audio (RMS, silence, overlap) + text (semantic from transcript)
    semantic = telemetry.semantic_score
    combined = 0.4 * rms_score + 0.25 * silence_score + 0.15 * overlap_score + 0.2 * semantic
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
            # Drain queue each tick so we compute from the freshest sample.
            # This prevents backlog growth when audio chunks arrive faster than interval_sec.
            while True:
                try:
                    t = telemetry_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if t is None:
                    return
                last_telemetry = t
            if last_telemetry is not None:
                score = compute_tension_from_telemetry(last_telemetry, state)
                on_tension(score)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        pass
