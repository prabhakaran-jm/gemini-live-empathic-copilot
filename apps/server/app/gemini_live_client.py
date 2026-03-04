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
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Env vars for real client
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_REGION = os.environ.get("GOOGLE_CLOUD_REGION", "europe-west1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-live-2.5-flash-native-audio")
GOOGLE_API_KEY = os.environ.get("GOOGLE_GENAI_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
LIVE_BACKCHANNEL = os.environ.get("LIVE_BACKCHANNEL", "1").strip().lower() in ("1", "true", "yes")
# Default dict config for main session; typed config can be re-enabled with GEMINI_LIVE_USE_DICT_CONFIG=0.
# This is more resilient across SDK variants for realtime transcription fields.
GEMINI_LIVE_USE_DICT_CONFIG = os.environ.get("GEMINI_LIVE_USE_DICT_CONFIG", "1").strip().lower() in ("1", "true", "yes")


# --- Events yielded by recv_events() ---

@dataclass
class LiveEvent:
    """One event from the live session."""
    kind: str  # "transcript_delta" | "user_transcript_delta" | "backchannel_audio" | "agent_output_started" | "agent_output_stopped" | "error"
    text: str = ""
    message: str = ""
    audio_base64: str = ""  # base64-encoded PCM audio (for backchannel_audio events)


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

    # Optional activity controls for realtime audio streaming/VAD nudging.
    async def start_activity(self) -> None:
        await asyncio.sleep(0)

    async def end_activity(self) -> None:
        await asyncio.sleep(0)

    async def end_audio_stream(self) -> None:
        await asyncio.sleep(0)


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
        self._activity_started = False
        self._sent_audio_chunks = 0
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
            if not self._activity_started:
                await self.start_activity()
            await self._session.send_realtime_input(
                audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
            )
            self._sent_audio_chunks += 1
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
            self._activity_started = False
        except Exception:
            pass

    async def start_activity(self) -> None:
        if self._closed or self._activity_started:
            return
        try:
            from google.genai import types
            await self._session.send_realtime_input(activity_start=types.ActivityStart())
            self._activity_started = True
        except Exception as e:
            logger.debug("start_activity failed: %s", e)

    async def end_activity(self) -> None:
        if self._closed or not self._activity_started:
            return
        try:
            from google.genai import types
            await self._session.send_realtime_input(activity_end=types.ActivityEnd())
        except Exception as e:
            logger.debug("end_activity failed: %s", e)
        finally:
            self._activity_started = False

    async def end_audio_stream(self) -> None:
        if self._closed:
            return
        try:
            await self._session.send_realtime_input(audio_stream_end=True)
        except Exception as e:
            logger.debug("end_audio_stream failed: %s", e)

    def _extract_transcript_from_obj(self, obj: object, seen: set | None = None) -> list[str]:
        """Recursively extract transcript-like strings from SDK response objects (for API variants)."""
        if seen is None:
            seen = set()
        if id(obj) in seen or obj is None:
            return []
        seen.add(id(obj))
        out: list[str] = []
        if isinstance(obj, str) and obj.strip():
            out.append(obj.strip())
            return out
        for name in ("text", "transcript", "content"):
            val = getattr(obj, name, None)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
        for name in ("parts", "content", "input_transcription", "input_audio_transcription"):
            val = getattr(obj, name, None)
            if isinstance(val, (list, tuple)):
                for item in val:
                    out.extend(self._extract_transcript_from_obj(item, seen))
        return out

    async def _receive_loop(self) -> None:
        """Consume session.receive() and push LiveEvents to _event_queue."""
        _log_structure_once = True
        _total_msgs = 0
        logger.info("_receive_loop started")
        try:
            async for msg in self._session.receive():
                _total_msgs += 1
                if self._closed:
                    break
                sc = getattr(msg, "server_content", None)
                # Per-message diagnostic at INFO (throttle: first 20, then every 50th)
                _msg_count = _total_msgs - 1
                if _msg_count < 20 or _msg_count % 50 == 0:
                    logger.info(
                        "recv msg #%s: type=%s, has_server_content=%s, has_text=%s",
                        _msg_count,
                        type(msg).__name__,
                        sc is not None,
                        bool(getattr(msg, "text", None)),
                    )
                # Log top-level msg and server_content structure once to find where transcription lives
                if _log_structure_once:
                    try:
                        msg_attrs = [a for a in dir(msg) if not a.startswith("_")]
                        logger.info("recv msg top-level attrs: %s", msg_attrs)
                        if sc is not None:
                            sc_attrs = [a for a in dir(sc) if not a.startswith("_")]
                            logger.info("server_content attrs: %s", sc_attrs)
                        _log_structure_once = False
                    except Exception:
                        pass
                emitted_this_msg = False
                if sc is not None:
                    # --- input_audio_transcription results (native-audio models) ---
                    # User's speech transcribed; use user_transcript_delta so recv_events() won't treat as agent output.
                    # API may use input_transcription or input_audio_transcription.
                    input_tx = getattr(sc, "input_transcription", None) or getattr(
                        sc, "input_audio_transcription", None
                    )
                    if input_tx:
                        # Single text field (use only if parts not present to avoid duplicate)
                        tx_text = (
                            getattr(input_tx, "text", None)
                            or getattr(input_tx, "transcript", None)
                            or (getattr(input_tx, "content", None) if isinstance(getattr(input_tx, "content", None), str) else None)
                        )
                        parts = getattr(input_tx, "parts", None)
                        if parts and isinstance(parts, (list, tuple)):
                            for part in parts:
                                p_text = getattr(part, "text", None) or getattr(part, "content", None)
                                if p_text:
                                    pt = p_text if isinstance(p_text, str) else str(p_text)
                                    logger.debug("Live transcript (part): %s", pt[:80] + "..." if len(pt) > 80 else pt)
                                    self._event_queue.put_nowait(
                                        LiveEvent(kind="user_transcript_delta", text=pt)
                                    )
                                    emitted_this_msg = True
                        elif tx_text:
                            ev_text = tx_text if isinstance(tx_text, str) else str(tx_text)
                            logger.debug("Live transcript (single): %s", ev_text[:80] + "..." if len(ev_text) > 80 else ev_text)
                            self._event_queue.put_nowait(
                                LiveEvent(kind="user_transcript_delta", text=ev_text)
                            )
                    # Fallback: try other known names for input transcription (SDK/API variants)
                    emitted_input = bool(input_tx)
                    for attr in ("realtime_input_transcription", "realtime_input_audio_transcription"):
                        input_tx_alt = getattr(sc, attr, None)
                        if input_tx_alt and input_tx_alt is not input_tx:
                            alt_text = (
                                getattr(input_tx_alt, "text", None)
                                or getattr(input_tx_alt, "transcript", None)
                                or (getattr(input_tx_alt, "content", None) if isinstance(getattr(input_tx_alt, "content", None), str) else None)
                            )
                            if alt_text:
                                self._event_queue.put_nowait(
                                    LiveEvent(kind="user_transcript_delta", text=alt_text if isinstance(alt_text, str) else str(alt_text))
                                )
                                emitted_input = True
                                emitted_this_msg = True
                                break
                    # Fallback: recursively scan input-transcription-like attrs only (SDK structure may vary)
                    if not emitted_input:
                        for attr in (
                            "input_transcription", "input_audio_transcription",
                            "realtime_input_transcription", "realtime_input_audio_transcription",
                        ):
                            obj = getattr(sc, attr, None)
                            if obj is None:
                                continue
                            for text in self._extract_transcript_from_obj(obj):
                                if text and len(text) < 5000:  # sanity: user utterance, not huge blob
                                    self._event_queue.put_nowait(LiveEvent(kind="user_transcript_delta", text=text))
                                    logger.info("Live transcript (fallback): %s", text[:80] + "..." if len(text) > 80 else text)
                                    emitted_input = True
                                    emitted_this_msg = True
                                    break
                            if emitted_input:
                                break
                    # --- model_turn: text parts + audio (backchannel) ---
                    mt = getattr(sc, "model_turn", None)
                    if mt and getattr(mt, "parts", None):
                        audio_chunks: list[bytes] = []
                        for part in mt.parts:
                            # Text content (transcript)
                            t = getattr(part, "text", None) or getattr(part, "content", None)
                            if t:
                                self._event_queue.put_nowait(
                                    LiveEvent(kind="transcript_delta", text=t if isinstance(t, str) else str(t))
                                )
                            # Audio content (backchannel from native-audio model)
                            inline = getattr(part, "inline_data", None)
                            if inline is not None:
                                data = getattr(inline, "data", None)
                                if isinstance(data, (bytes, bytearray)):
                                    audio_chunks.append(bytes(data))
                        # Emit collected audio as a single backchannel event
                        if audio_chunks and LIVE_BACKCHANNEL:
                            raw = b"".join(audio_chunks)
                            b64 = base64.b64encode(raw).decode("ascii")
                            self._event_queue.put_nowait(
                                LiveEvent(kind="backchannel_audio", audio_base64=b64)
                            )
                    if getattr(sc, "interrupted", None) or getattr(sc, "turn_complete", None):
                        self._event_queue.put_nowait(LiveEvent(kind="agent_output_stopped"))
                    # Some SDK variants surface transcriptions under output_* fields.
                    output_tx = getattr(sc, "output_transcription", None) or getattr(
                        sc, "output_audio_transcription", None
                    )
                    if output_tx:
                        output_text = (
                            getattr(output_tx, "text", None)
                            or getattr(output_tx, "transcript", None)
                            or (getattr(output_tx, "content", None) if isinstance(getattr(output_tx, "content", None), str) else None)
                        )
                        if output_text:
                            self._event_queue.put_nowait(
                                LiveEvent(
                                    kind="transcript_delta",
                                    text=output_text if isinstance(output_text, str) else str(output_text),
                                )
                            )
                # --- top-level .text shorthand ---
                if getattr(msg, "text", None) and msg.text:
                    self._event_queue.put_nowait(
                        LiveEvent(kind="transcript_delta", text=msg.text)
                    )
                # --- top-level transcript-like fields (transcription may live on msg, not server_content) ---
                if not emitted_this_msg:
                    for attr in ("input_transcription", "input_audio_transcription", "realtime_input_transcription", "realtime_input_audio_transcription"):
                        obj = getattr(msg, attr, None)
                        if obj is None:
                            continue
                        for text in self._extract_transcript_from_obj(obj):
                            if text and len(text) < 5000:
                                self._event_queue.put_nowait(LiveEvent(kind="user_transcript_delta", text=text))
                                logger.info("Live transcript (top-level %s): %s", attr, text[:80] + "..." if len(text) > 80 else text)
                                break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closed:
                self._event_queue.put_nowait(LiveEvent(kind="error", message=str(e)))
        finally:
            if _total_msgs == 0 and self._sent_audio_chunks > 0:
                logger.warning(
                    "Gemini Live returned 0 recv messages after %s audio chunks. "
                    "Likely config/region transcription mismatch.",
                    self._sent_audio_chunks,
                )
            logger.info("_receive_loop ended (received %s messages from Gemini Live)", _total_msgs)
            self._event_queue.put_nowait(None)

    async def recv_events(self) -> AsyncIterator[LiveEvent]:
        """Async iterator of events. Emit agent_output_started on first agent content, agent_output_stopped on turn complete.

        user_transcript_delta events (from input_audio_transcription) pass through
        without triggering agent_output_started — they are the user's own speech.
        """
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
            # user_transcript_delta and backchannel_audio: pass through without agent-speaking logic
            if ev.kind in ("user_transcript_delta", "backchannel_audio"):
                yield ev
                continue
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
        model = config.model
        is_native_audio = "native-audio" in model

        system_text = (
            "You are an empathetic listening companion in a real-time conversation. "
            "Your role is minimal backchannel feedback only. "
            "Rules:\n"
            "- Respond ONLY with very short acknowledgments: 'Mmhm', 'I see', 'Go on', 'Right', 'Okay', 'Yeah'.\n"
            "- NEVER say more than 3 words at a time.\n"
            "- NEVER give advice, opinions, questions, or commentary.\n"
            "- NEVER repeat or paraphrase what the user said.\n"
            "- Respond infrequently — only every 10-15 seconds of user speech, not after every sentence.\n"
            "- Use a calm, soft, gentle tone.\n"
            "- If unsure, stay silent. Silence is always acceptable."
        ) if LIVE_BACKCHANNEL else (
            "You are an invisible listening assistant. "
            "Your ONLY job is to transcribe what the user says. "
            "Do NOT speak, do NOT generate audio output, do NOT respond. "
            "Stay completely silent."
        )
        live_config = None
        if is_native_audio:
            dict_config = {
                # For Live transcription, docs require text to be included in response_modalities.
                "response_modalities": ["audio", "text"],
                "speech_config": {
                    "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
                },
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "realtime_input_config": {
                    "automatic_activity_detection": {
                        "disabled": False,
                    }
                },
                "system_instruction": {"parts": [{"text": system_text}]},
            }
            if GEMINI_LIVE_USE_DICT_CONFIG:
                live_config = dict_config
                logger.info("Using dict config for main session (GEMINI_LIVE_USE_DICT_CONFIG=1)")
            else:
                # Prefer typed LiveConnectConfig so input_audio_transcription is reliably passed (dict may be lossy).
                try:
                    from google.genai import types
                    kwargs = {
                        # For Live transcription, include text alongside audio.
                        "response_modalities": ["audio", "text"],
                        "speech_config": types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                            )
                        ),
                        "system_instruction": types.Content(parts=[types.Part.from_text(text=system_text)]),
                    }
                    # SDK expects AudioTranscriptionConfig for input/output transcription.
                    atc_cls = getattr(types, "AudioTranscriptionConfig", None)
                    if atc_cls is not None:
                        kwargs["input_audio_transcription"] = atc_cls()
                        kwargs["output_audio_transcription"] = atc_cls()
                    else:
                        logger.warning(
                            "AudioTranscriptionConfig not found in SDK; typed config may omit transcription"
                        )
                    aad_cls = getattr(types, "AutomaticActivityDetection", None)
                    ric_cls = getattr(types, "RealtimeInputConfig", None)
                    if aad_cls is not None and ric_cls is not None:
                        kwargs["realtime_input_config"] = ric_cls(
                            automatic_activity_detection=aad_cls(disabled=False)
                        )
                    else:
                        logger.warning(
                            "RealtimeInputConfig/AutomaticActivityDetection not found in SDK; "
                            "typed config may rely on defaults for VAD"
                        )
                    live_config = types.LiveConnectConfig(**kwargs)
                    logger.info("Using LiveConnectConfig (typed) for main session")
                except Exception as e:
                    logger.warning("LiveConnectConfig build failed, using dict config: %s", e)
                    live_config = dict_config
        if not is_native_audio:
            # Non-native models (e.g. gemini-2.0-flash-exp) support TEXT modality.
            # Do NOT include speech_config with TEXT — they are incompatible.
            live_config = {
                "response_modalities": ["text"],
            }

        logger.info("Connecting to Gemini Live: model=%s, native_audio=%s", model, is_native_audio)
        cm = client.aio.live.connect(model=model, config=live_config)
        session = await cm.__aenter__()
        real_session = RealGeminiLiveSession(config, session, cm)
        asyncio.create_task(real_session._receive_loop())
        return real_session


async def generate_whisper_audio(text: str) -> str | None:
    """
    Generate a short audio whisper for the given text using a short-lived Gemini Live session.

    Returns base64-encoded PCM16 mono 24 kHz audio, or None on failure.
    """
    # Require either explicit API key or project for ADC; otherwise, skip Live audio.
    if not (GOOGLE_API_KEY or GOOGLE_CLOUD_PROJECT):
        return None

    try:
        from google.genai import types
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("generate_whisper_audio: google-genai not available: %s", e)
        return None

    try:
        client = _make_genai_client()
    except Exception as e:
        logger.warning("generate_whisper_audio: failed to build client: %s", e)
        return None

    model = GEMINI_MODEL

    try:
        tts_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            system_instruction=types.Content(
                parts=[
                    types.Part.from_text(
                        text=(
                            "You are a soft-spoken coach. Read the user's text aloud exactly as written, "
                            "in a calm whispered tone. Do not add any words."
                        )
                    )
                ]
            ),
        )
    except Exception as e:
        logger.warning("generate_whisper_audio: failed to build LiveConnectConfig: %s", e)
        return None

    audio_chunks: list[bytes] = []

    cm = client.aio.live.connect(model=model, config=tts_config)
    session = await cm.__aenter__()
    try:
        await session.send(input=text, end_of_turn=True)

        async for msg in session.receive():
            sc = getattr(msg, "server_content", None)
            if sc is None:
                continue
            mt = getattr(sc, "model_turn", None)
            if not mt:
                continue
            parts = getattr(mt, "parts", None)
            if not parts:
                continue
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None:
                    data = getattr(inline, "data", None)
                    if isinstance(data, (bytes, bytearray)):
                        audio_chunks.append(bytes(data))
    except Exception as e:
        logger.exception("generate_whisper_audio: error during TTS session: %s", e)
        return None
    finally:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            # Best-effort close
            pass

    if not audio_chunks:
        return None

    raw = b"".join(audio_chunks)
    try:
        return base64.b64encode(raw).decode("ascii")
    except Exception as e:
        logger.warning("generate_whisper_audio: failed to base64-encode audio: %s", e)
        return None


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
