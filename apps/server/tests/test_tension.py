"""
Unit tests for tension scoring: compute_tension_from_telemetry and TensionState.
"""
import asyncio
import pytest

from app.tension import (
    AudioTelemetry,
    TensionState,
    compute_semantic_tension,
    compute_tension_from_telemetry,
    compute_tension_loop,
    ESCALATION_MARKERS,
)


def test_tension_low_rms_speech():
    """Low RMS with no silence/overlap yields low tension."""
    state = TensionState()
    t = AudioTelemetry(rms=0.1, is_silence=False, is_overlap=False, ts=1000.0)
    score = compute_tension_from_telemetry(t, state)
    assert 0 <= score <= 30


def test_tension_high_rms_increases_score():
    """Higher RMS (loud speech) increases tension component."""
    state = TensionState()
    t_low = AudioTelemetry(rms=0.2, is_silence=False, is_overlap=False, ts=1000.0)
    t_high = AudioTelemetry(rms=0.9, is_silence=False, is_overlap=False, ts=1001.0)
    compute_tension_from_telemetry(t_low, state)
    score = compute_tension_from_telemetry(t_high, state)
    assert score >= 40


def test_tension_silence_accumulates():
    """Prolonged silence increases silence_score component."""
    state = TensionState()
    base_ts = 1000.0
    # Start silence
    t0 = AudioTelemetry(rms=0.02, is_silence=True, is_overlap=False, ts=base_ts)
    compute_tension_from_telemetry(t0, state)
    # Continue silence past threshold (2.5s)
    t1 = AudioTelemetry(rms=0.02, is_silence=True, is_overlap=False, ts=base_ts + 3.0)
    score = compute_tension_from_telemetry(t1, state)
    assert score >= 20


def test_tension_overlap_increases_score():
    """Multiple overlap (barge-in) events increase overlap_score (recent timestamps only)."""
    state = TensionState()
    for i in range(4):
        t = AudioTelemetry(rms=0.5, is_silence=False, is_overlap=True, ts=1000.0 + i)
        compute_tension_from_telemetry(t, state)
    # overlap_timestamps has 4 entries within 10s; overlap_score = min(1.0, 0.8) = 0.8
    score = compute_tension_from_telemetry(
        AudioTelemetry(rms=0.5, is_silence=False, is_overlap=False, ts=1005.0), state
    )
    assert score >= 30


def test_overlap_decays_over_time():
    """Old overlaps (>10s) are not counted; tension can recover after calm period."""
    state = TensionState()
    # One overlap at t=0
    compute_tension_from_telemetry(
        AudioTelemetry(rms=0.3, is_silence=False, is_overlap=True, ts=0.0), state
    )
    # 15 seconds later, calm speech (no overlap)
    calm = AudioTelemetry(rms=0.1, is_silence=False, is_overlap=False, ts=15.0)
    score = compute_tension_from_telemetry(calm, state)
    # Overlap at t=0 is older than 10s, so trimmed; overlap_score=0, score should be low
    assert score < 20


def test_tension_bounded_0_100():
    """Score is always in [0, 100]."""
    state = TensionState()
    for rms in [0.0, 0.5, 1.0]:
        for overlap in [True, False]:
            t = AudioTelemetry(rms=rms, is_silence=False, is_overlap=overlap, ts=1000.0)
            score = compute_tension_from_telemetry(t, state)
            assert 0 <= score <= 100


@pytest.mark.asyncio
async def test_tension_loop_stops_on_none():
    """compute_tension_loop exits when None is put in queue."""
    queue: asyncio.Queue = asyncio.Queue()
    state = TensionState()
    scores: list[int] = []

    def on_tension(score: int) -> None:
        scores.append(score)

    task = asyncio.create_task(
        compute_tension_loop(queue, state, on_tension, interval_sec=0.05)
    )
    queue.put_nowait(AudioTelemetry(rms=0.3, is_silence=False, is_overlap=False, ts=1000.0))
    await asyncio.sleep(0.12)  # allow at least 2 ticks so one computes tension
    queue.put_nowait(None)
    await task
    assert len(scores) >= 1


# --- Semantic tension (4th signal) ---


def test_semantic_tension_empty_returns_zero():
    """No transcript text yields 0 semantic tension."""
    assert compute_semantic_tension("") == 0.0
    assert compute_semantic_tension(None) == 0.0


def test_semantic_tension_no_markers():
    """Neutral text yields 0 semantic tension."""
    assert compute_semantic_tension("I think we should talk about the project timeline") == 0.0


def test_semantic_tension_single_marker():
    """One escalation marker yields 0.25."""
    # Use a phrase that matches only one marker (e.g. "ridiculous" only; "always" + "you always" would be 2)
    assert compute_semantic_tension("This is ridiculous") == 0.25


def test_semantic_tension_multiple_markers():
    """Multiple markers accumulate (0.25 each, capped at 1.0)."""
    text = "You always do this, you never listen, it's your fault, whatever"
    score = compute_semantic_tension(text)
    assert score >= 0.75  # at least 3 hits: "always", "you never", "your fault", "whatever"


def test_semantic_tension_capped_at_one():
    """Score cannot exceed 1.0 regardless of marker count."""
    text = " ".join(ESCALATION_MARKERS[:10])  # many markers
    assert compute_semantic_tension(text) == 1.0


def test_semantic_tension_case_insensitive():
    """Matching is case-insensitive."""
    assert compute_semantic_tension("This is RIDICULOUS") == 0.25


def test_semantic_tension_uses_last_200_chars():
    """Only the last ~200 characters are analyzed."""
    padding = "a " * 200  # >200 chars of neutral text
    text = "you always do this " + padding
    # "you always" is beyond the 200-char tail
    assert compute_semantic_tension(text) == 0.0
