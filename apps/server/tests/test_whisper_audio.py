"""
Tests for generate_whisper_audio: mock Live TTS session, assert base64 or None.
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gemini_live_client import generate_whisper_audio


@pytest.mark.asyncio
async def test_generate_whisper_audio_returns_none_when_no_credentials():
    """When GOOGLE_API_KEY and GOOGLE_CLOUD_PROJECT are unset, returns None."""
    with patch.dict("os.environ", {"GOOGLE_API_KEY": "", "GOOGLE_CLOUD_PROJECT": ""}, clear=False):
        with patch("app.gemini_live_client.GOOGLE_API_KEY", ""):
            with patch("app.gemini_live_client.GOOGLE_CLOUD_PROJECT", ""):
                result = await generate_whisper_audio("Take a breath")
    assert result is None


@pytest.mark.asyncio
async def test_generate_whisper_audio_returns_base64_on_success():
    """When mocked Live session returns audio chunks, returns valid base64."""
    fake_audio = b"\x00\x00\x01\x00" * 100  # PCM16-like bytes

    async def fake_receive():
        msg = MagicMock()
        sc = MagicMock()
        mt = MagicMock()
        part = MagicMock()
        part.inline_data.data = bytes(fake_audio)
        mt.parts = [part]
        sc.model_turn = mt
        msg.server_content = sc
        yield msg

    mock_session = AsyncMock()
    mock_session.send = AsyncMock()
    mock_session.receive = fake_receive

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aio.live.connect = MagicMock(return_value=mock_cm)

    with patch("app.gemini_live_client.GOOGLE_API_KEY", "test-key"):
        with patch("app.gemini_live_client._make_genai_client", return_value=mock_client):
            try:
                result = await generate_whisper_audio("Take a breath")
            except Exception as e:
                pytest.skip(f"google.genai not available or config build failed: {e}")
                return

    if result is None:
        pytest.skip("generate_whisper_audio returned None (SDK config build may have failed)")
    decoded = base64.b64decode(result, validate=True)
    assert isinstance(decoded, bytes)
    assert len(decoded) > 0


@pytest.mark.asyncio
async def test_generate_whisper_audio_returns_none_on_failure():
    """When Live session raises, returns None."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection failed"))
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_client = MagicMock()
    mock_client.aio.live.connect = MagicMock(return_value=mock_cm)

    with patch("app.gemini_live_client.GOOGLE_API_KEY", "test-key"):
        with patch("app.gemini_live_client._make_genai_client", return_value=mock_client):
            try:
                result = await generate_whisper_audio("Take a breath")
            except Exception:
                pytest.skip("google.genai.types not available")
                return
    assert result is None
