"""
Gemini Live API client: real implementation (google-genai) + stub for tests/mock.
Audio: PCM16 mono 16 kHz. Server receives base64-encoded PCM16 from client; session accepts bytes.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# Env vars for real client
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_REGION = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
GOOGLE_API_KEY = os.environ.get("GOOGLE_GENAI_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


# --- Events yielded by recv_events() ---

@dataclass
class LiveEvent:
    """One event from the live session."""
    kind: str  # "transcript_delta" | "agent_output_started" | "agent_output_stopped" | "error"
    text: str = ""
    message: str = ""


# --- Config and interfaces ---

@dataclass
class LiveSessionConfig:
    """Configuration for a single Gemini Live session."""
    model: str = GEMINI_MODEL
    sample_rate_hz: int = 16000


@dataclass
class AgentTurn:
    """One agent response (for stub compatibility). Coaching text comes from app/coaching.py only."""
    text: str = ""
    move: str = ""
    audio_base64: str = ""
    is_final: bool = False


class IGeminiLiveClient(ABC):
    """Interface for Gemini Live bidi streaming."""

    @abstractmethod
    async def connect(self, config: LiveSessionConfig) -> "IGeminiLiveSession":
        """Establish bidi connection. Caller must call close() when done."""
        ...


class IGeminiLiveSession(ABC):
    """One live session: send audio, receive events. Supports barge-in."""

    @abstractmethod
    async def send_audio(self, pcm_base64: str) -> None:
        """Send one chunk of audio (base64-encoded PCM16 16kHz mono)."""
        ...

    @abstractmethod
    async def stop_generation(self) -> None:
        """Barge-in: stop current agent output. Next send_audio continues."""
        ...

    @abstractmethod
    async def recv_events(self) -> AsyncIterator[LiveEvent]:
        """Async iterator of events: transcript_delta, agent_output_started/stopped, error."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close session and release resources."""
        ...

    # Optional: stub may implement agent_turns for injected whispers; real client does not.
    async def agent_turns(self) -> AsyncIterator[AgentTurn]:
        """Empty by default. Stub overrides to inject turns. Coaching from app/coaching.py only."""
        if False:
            yield


# --- Real implementation (google-genai) ---

def _make_genai_client():
    """Build genai.Client from env: Vertex (ADC) or API key."""
    try:
        from google import genai
    except ImportError as e:
        raise ImportError(
            "Real Gemini Live client requires google-genai. Install with: pip install google-genai"
        ) from e
    if GOOGLE_API_KEY:
        return genai.Client(api_key=GOOGLE_API_KEY)
    if GOOGLE_CLOUD_PROJECT:
        return genai.Client(
            vertexai=True,
            project=GOOGLE_CLOUD_PROJECT,
            location=GOOGLE_CLOUD_REGION,
        )
    return genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=GOOGLE_CLOUD_REGION,
    )


class RealGeminiLiveSession(IGeminiLiveSession):
    """Real session using google-genai Live API. Coaching text is NOT from model; use app/coaching.py."""

    def __init__(self, config: LiveSessionConfig, _session, _cm):
        self._config = config
        self._session = _session  # genai AsyncSession
        self._cm = _cm  # async context manager, for __aexit__ on close
        self._closed = False
        self._interrupted = False
        self._event_queue: asyncio.Queue[LiveEvent | None] = asyncio.Queue()

    async def send_audio(self, pcm_base64: str) -> None:
        if self._closed:
            return
        try:
            raw = base64.b64decode(pcm_base64, validate=True)
        except Exception:
            return
        try:
            from google.genai import types
            await self._session.send_realtime_input(
                audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
            )
        except Exception as e:
            logger.warning("send_realtime_input failed: %s", e)
            self._event_queue.put_nowait(LiveEvent(kind="error", message=str(e)))

    async def stop_generation(self) -> None:
        """Set interrupted flag; signal API to stop. New user audio will resume."""
        self._interrupted = True
        try:
            from google.genai import types
            await self._session.send_realtime_input(
                activity_end=types.ActivityEnd()
            )
        except Exception:
            pass

    async def _receive_loop(self) -> None:
        """Consume session.receive() and push LiveEvents to _event_queue."""
        try:
            async for msg in self._session.receive():
                if self._closed:
                    break
                sc = getattr(msg, "server_content", None)
                if sc is not None:
                    # Transcript / model output
                    mt = getattr(sc, "model_turn", None)
                    if mt and getattr(mt, "parts", None):
                        for part in mt.parts:
                            t = getattr(part, "text", None) or getattr(part, "content", None)
                            if t:
                                self._event_queue.put_nowait(
                                    LiveEvent(kind="transcript_delta", text=t if isinstance(t, str) else str(t))
                                )
                    if getattr(sc, "interrupted", None) or getattr(sc, "turn_complete", None):
                        self._event_queue.put_nowait(LiveEvent(kind="agent_output_stopped"))
                if getattr(msg, "text", None) and msg.text:
                    self._event_queue.put_nowait(
                        LiveEvent(kind="transcript_delta", text=msg.text)
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closed:
                self._event_queue.put_nowait(LiveEvent(kind="error", message=str(e)))
        finally:
            self._event_queue.put_nowait(None)

    async def recv_events(self) -> AsyncIterator[LiveEvent]:
        """Async iterator of events. Emit agent_output_started on first content, agent_output_stopped on turn complete."""
        agent_speaking = False
        while not self._closed:
            try:
                ev = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            if ev is None:
                return
            if ev.kind == "transcript_delta" and not agent_speaking:
                agent_speaking = True
                yield LiveEvent(kind="agent_output_started")
            yield ev
            if ev.kind == "agent_output_stopped":
                agent_speaking = False

    async def close(self) -> None:
        self._closed = True
        self._event_queue.put_nowait(None)
        try:
            await self._session.close()
        except Exception:
            pass
        try:
            await self._cm.__aexit__(None, None, None)
        except Exception:
            pass

    async def disconnect(self) -> None:
        """Alias for close() for handler compatibility."""
        await self.close()


class RealGeminiLiveClient(IGeminiLiveClient):
    """Real client: one Gemini Live session per browser WS. Uses GOOGLE_CLOUD_* or API key."""

    async def connect(self, config: LiveSessionConfig) -> IGeminiLiveSession:
        client = _make_genai_client()
        live_config = {
            "response_modalities": ["TEXT"],
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
            },
        }
        cm = client.aio.live.connect(model=config.model, config=live_config)
        session = await cm.__aenter__()
        real_session = RealGeminiLiveSession(config, session, cm)
        asyncio.create_task(real_session._receive_loop())
        return real_session


# --- Stub implementation ---

class StubGeminiLiveSession(IGeminiLiveSession):
    """Stub: no real Gemini. Used when MOCK=1 or for tests."""

    def __init__(self, config: LiveSessionConfig) -> None:
        self._config = config
        self._closed = False
        self._turn_queue: asyncio.Queue[AgentTurn | None] = asyncio.Queue()
        self._event_queue: asyncio.Queue[LiveEvent | None] = asyncio.Queue()

    async def send_audio(self, pcm_base64: str) -> None:
        if self._closed:
            return
        await asyncio.sleep(0)

    async def stop_generation(self) -> None:
        await asyncio.sleep(0)

    async def recv_events(self) -> AsyncIterator[LiveEvent]:
        while not self._closed:
            try:
                ev = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                if ev is None:
                    return
                yield ev
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        self._closed = True
        await self._event_queue.put(None)

    async def disconnect(self) -> None:
        await self.close()

    async def agent_turns(self) -> AsyncIterator[AgentTurn]:
        while not self._closed:
            try:
                turn = await asyncio.wait_for(self._turn_queue.get(), timeout=0.1)
                if turn is None:
                    return
                yield turn
            except asyncio.TimeoutError:
                continue

    def inject_turn(self, turn: AgentTurn) -> None:
        if not self._closed:
            self._turn_queue.put_nowait(turn)


class StubGeminiLiveClient(IGeminiLiveClient):
    async def connect(self, config: LiveSessionConfig) -> IGeminiLiveSession:
        return StubGeminiLiveSession(config)


# --- Factory ---

def get_gemini_client() -> IGeminiLiveClient:
    """Return real client when GOOGLE_CLOUD_PROJECT or API key is set; otherwise stub. Handler uses stub when MOCK=1."""
    if GOOGLE_CLOUD_PROJECT or GOOGLE_API_KEY:
        return RealGeminiLiveClient()
    return StubGeminiLiveClient()
