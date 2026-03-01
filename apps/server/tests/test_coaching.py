"""
Unit tests for coaching: get_move_by_id, fallback mapping, and generate_coaching fallback.
"""
import asyncio
from unittest.mock import patch

import pytest

from app.coaching import (
    COACHING_MOVES,
    FALLBACK_MOVES,
    get_move_by_id,
    generate_coaching,
)


def test_get_move_by_id_returns_move():
    """get_move_by_id returns the correct move dict for known ids."""
    for m in COACHING_MOVES:
        move_id = m["move"]
        got = get_move_by_id(move_id)
        assert got is not None
        assert got["move"] == move_id
        assert "text" in got and len(got["text"]) > 0


def test_get_move_by_id_unknown_returns_none():
    """get_move_by_id returns None for unknown id."""
    assert get_move_by_id("nonexistent") is None


def test_fallback_moves_cover_triggers():
    """FALLBACK_MOVES maps each trigger to a valid move id in COACHING_MOVES."""
    move_ids = {m["move"] for m in COACHING_MOVES}
    for trigger, move_id in FALLBACK_MOVES.items():
        assert move_id in move_ids, f"FALLBACK_MOVES[{trigger!r}] = {move_id!r} not in COACHING_MOVES"


@pytest.mark.asyncio
async def test_generate_coaching_returns_fallback_on_failure():
    """When AI generation fails, generate_coaching returns a fixed fallback phrase."""
    with patch("app.coaching._get_flash_client") as mock_get:
        mock_get.side_effect = RuntimeError("No API key")
        result = await generate_coaching(
            trigger="tension_cross",
            tension_score=50,
            transcript_buffer="They never listen.",
        )
    assert isinstance(result, dict)
    assert "move" in result and "text" in result
    assert result["move"] == FALLBACK_MOVES.get("tension_cross", "slow_down")
    assert result["text"]  # non-empty fallback text


@pytest.mark.asyncio
async def test_generate_coaching_fallback_barge_in():
    """Fallback for barge_in trigger uses reflect_back."""
    with patch("app.coaching._get_flash_client") as mock_get:
        mock_get.side_effect = Exception("Network error")
        result = await generate_coaching(
            trigger="barge_in",
            tension_score=30,
            transcript_buffer="",
        )
    assert result["move"] == "reflect_back"
    assert "text" in result and len(result["text"]) > 0


@pytest.mark.asyncio
async def test_generate_coaching_fallback_post_escalation_silence():
    """Fallback for post_escalation_silence uses clarify_intent."""
    with patch("app.coaching._get_flash_client") as mock_get:
        mock_get.side_effect = Exception("Timeout")
        result = await generate_coaching(
            trigger="post_escalation_silence",
            tension_score=80,
            transcript_buffer="",
        )
    assert result["move"] == "clarify_intent"
    assert "text" in result
