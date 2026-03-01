"""
Unit tests for tension scoring: compute_tension_from_telemetry and TensionState.
"""
import asyncio
import pytest

from app.tension import (
    AudioTelemetry,
    TensionState,
    compute_tension_from_telemetry,
    compute_tension_loop,
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
    """Multiple overlap (barge-in) events increase overlap_score."""
    state = TensionState()
    for i in range(4):
        t = AudioTelemetry(rms=0.5, is_silence=False, is_overlap=True, ts=1000.0 + i)
        compute_tension_from_telemetry(t, state)
    # overlap_score caps at 1.0 (0.2 * 4 = 0.8), combined with rms
    score = compute_tension_from_telemetry(
        AudioTelemetry(rms=0.5, is_silence=False, is_overlap=False, ts=1005.0), state
    )
    assert score >= 30


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
