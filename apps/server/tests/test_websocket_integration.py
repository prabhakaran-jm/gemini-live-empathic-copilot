"""
Integration tests: WebSocket /ws flow with mock backend (MOCK=1).
Verifies start -> ready, tension and whisper from mock loop, stop -> stopped, and error handling.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def mock_mode():
    """Force websocket_handler to use MOCK_MODE so no real Gemini connection is needed."""
    with patch.dict(os.environ, {"MOCK": "1"}, clear=False):
        with patch("app.websocket_handler.MOCK_MODE", True):
            yield


def _collect_messages(ws, max_messages: int = 10):
    """Collect up to max_messages from websocket (blocking)."""
    collected = []
    for _ in range(max_messages):
        try:
            data = ws.receive_json()
            collected.append(data)
        except Exception:
            break
    return collected


def test_ws_start_receives_ready(mock_mode):
    """Send start -> receive ready."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        data = ws.receive_json()
    assert data.get("type") == "ready"


def test_ws_mock_sends_tension(mock_mode):
    """With MOCK=1, after start we receive at least one tension message (mock sends every 2s)."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        _ = ws.receive_json()  # ready
        messages = _collect_messages(ws, max_messages=5)
    tension = [m for m in messages if m.get("type") == "tension"]
    assert len(tension) >= 1
    assert "score" in tension[0]
    assert 0 <= tension[0]["score"] <= 100


def test_ws_mock_sends_whisper(mock_mode):
    """With MOCK=1, after a few ticks we receive at least one whisper (mock sends every 3rd tick)."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        _ = ws.receive_json()  # ready
        messages = _collect_messages(ws, max_messages=6)
    whispers = [m for m in messages if m.get("type") == "whisper"]
    assert len(whispers) >= 1
    assert "text" in whispers[0] and "move" in whispers[0]


def test_ws_stop_receives_stopped(mock_mode):
    """Send start -> ready, then stop -> stopped."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        data = ws.receive_json()
        assert data.get("type") == "ready"
        ws.send_json({"type": "stop"})
        data = ws.receive_json()
    assert data.get("type") == "stopped"


def test_ws_invalid_json_returns_error(mock_mode):
    """Sending invalid JSON yields an error message."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        data = ws.receive_json()
    assert data.get("type") == "error"
    assert "message" in data


def test_ws_double_start_returns_error(mock_mode):
    """Sending start twice returns error 'Already started' on second start."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        data = ws.receive_json()
        assert data.get("type") == "ready"
        ws.send_json({"type": "start"})
        data = ws.receive_json()
    assert data.get("type") == "error"
    assert "Already started" in (data.get("message") or "")


def test_ws_frame_message_accepted(mock_mode):
    """After start, sending a frame message does not error; next message is still tension/whisper."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        data = ws.receive_json()
        assert data.get("type") == "ready"
        ws.send_json({"type": "frame", "base64": "fake_jpeg_base64_placeholder"})
        messages = _collect_messages(ws, max_messages=3)
    assert not any(m.get("type") == "error" for m in messages)
    assert any(m.get("type") in ("tension", "whisper") for m in messages)
