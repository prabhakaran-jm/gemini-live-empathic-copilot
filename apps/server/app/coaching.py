"""
Coaching moves: deterministic triggers + Gemini-generated contextual whispers.
Falls back to fixed 8-12 word phrases if generation fails.
Grounded in Nonviolent Communication (NVC) and active listening principles.
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

COACHING_MOVES: list[dict[str, str]] = [
    {
        "move": "reflect_back",
        "text": "It sounds like this is really important to you right now.",
    },
    {
        "move": "clarify_intent",
        "text": "Would it help to say what you're hoping they take away?",
    },
    {
        "move": "slow_down",
        "text": "Taking a breath before the next sentence can help.",
    },
    {
        "move": "deescalate_tone",
        "text": "A softer tone might make it easier for them to hear you.",
    },
    {
        "move": "invite_perspective",
        "text": "You could ask how they're seeing it so far.",
    },
]

FALLBACK_MOVES: dict[str, str] = {
    "tension_cross": "slow_down",
    "barge_in": "reflect_back",
    "post_escalation_silence": "clarify_intent",
}

COACHING_SYSTEM_PROMPT = """\
You are "Sage" — a calm, empathetic conversation coach who whispers guidance \
during difficult conversations. Your personality: warm but direct, emotionally \
intelligent, gently encouraging. Think of a trusted mentor who speaks softly \
but with clarity. You use Nonviolent Communication (NVC) and active listening.

The user is in a difficult conversation RIGHT NOW. Based on the transcript, \
tension level, trigger, and optionally their webcam image, generate ONE \
coaching whisper.

Rules:
- Exactly 8 to 12 words, no more
- Use NVC principles: observations, feelings, needs, requests
- Use active listening: reflect, validate, invite perspective
- Never diagnose, label, or judge either party
- Speak directly to the user in second person ("you")
- Be warm and concise — you're whispering in their ear during a live conversation
- IMPORTANT: Vary your phrasing. Don't start every whisper with "You look" or \
"You seem." Use diverse openings: questions, gentle imperatives, observations, \
reflections (e.g. "Try asking...", "Notice how...", "What if you...", \
"Their tone shifted — pause here.", "Share what you need right now.")
- If a webcam image is provided, read specific body language cues:
  * Facial tension (furrowed brow, clenched jaw, tight lips)
  * Posture (leaning forward aggressively, crossed arms, slumped shoulders)
  * Hand gestures (pointing, clenched fists, open palms)
  * Eye contact patterns (looking away, staring down)
  Reference these SPECIFICALLY, not generically. Say "Your jaw is tight — soften it" \
  not "You look tense."
- Output ONLY the whisper phrase, nothing else

Trigger types:
- tension_cross: tension just rose above threshold (conversation heating up)
- barge_in: 2+ interruptions detected (turn-taking friction)
- post_escalation_silence: awkward silence after high tension\
"""

COACHING_GROUNDING = os.environ.get("COACHING_GROUNDING", "0").strip().lower() in ("1", "true", "yes")

_flash_client = None


def _get_flash_client():
    """Build a google.genai.Client for standard (non-Live) generate_content calls."""
    global _flash_client
    if _flash_client is not None:
        return _flash_client
    try:
        from google import genai
    except ImportError as e:
        raise ImportError("google-genai required for coaching generation") from e

    api_key = (
        os.environ.get("GOOGLE_GENAI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if api_key:
        _flash_client = genai.Client(api_key=api_key)
    elif os.environ.get("GOOGLE_CLOUD_PROJECT"):
        _flash_client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"),
        )
    else:
        _flash_client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            location=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"),
        )
    return _flash_client


async def generate_coaching(
    trigger: str,
    tension_score: int,
    transcript_buffer: str,
    last_whisper: str = "",
    image_b64: str = "",
) -> dict[str, str]:
    """
    Call gemini-2.0-flash to produce a contextual coaching whisper.
    Returns {"move": trigger, "text": "..."}.

    When image_b64 is provided (webcam frame), includes it so coaching can
    reference visual cues (body language, facial expression, posture).
    When COACHING_GROUNDING is enabled, adds google_search tool so whispers
    can be grounded in NVC/conflict resolution research.

    Falls back to fixed phrase on any failure.
    """
    try:
        from google import genai

        client = _get_flash_client()
        avoid_line = ""
        if last_whisper:
            avoid_line = f"\nPrevious whisper (DO NOT repeat): \"{last_whisper}\"\n"
        user_prompt_text = (
            f"Trigger: {trigger}\n"
            f"Current tension: {tension_score}/100\n"
            f"Recent transcript:\n{transcript_buffer[-500:]}\n"
            f"{avoid_line}\n"
            f"Generate one coaching whisper (8-12 words):"
        )

        # Build content parts: text + optional vision frame
        content_parts: list = [user_prompt_text]
        if image_b64:
            try:
                image_bytes = base64.b64decode(image_b64)
                content_parts.append(
                    genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                )
                logger.info("Coaching with vision frame (%d KB)", len(image_bytes) // 1024)
            except Exception as img_err:
                logger.warning("Failed to decode vision frame, proceeding text-only: %s", img_err)

        # Build config with optional google_search grounding
        config_kwargs: dict = {
            "system_instruction": COACHING_SYSTEM_PROMPT,
            "max_output_tokens": 30,
            "temperature": 0.7,
        }
        if COACHING_GROUNDING:
            config_kwargs["tools"] = [genai.types.Tool(google_search=genai.types.GoogleSearch())]
            logger.debug("Coaching with Google Search grounding enabled")

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=content_parts,
            config=genai.types.GenerateContentConfig(**config_kwargs),
        )
        text = response.text.strip().strip('"').strip("'")
        word_count = len(text.split())
        if word_count < 4 or word_count > 20:
            raise ValueError(f"Unexpected word count: {word_count}")
        logger.info("AI coaching [%s]: %s", trigger, text)
        return {"move": trigger, "text": text}
    except Exception as e:
        logger.warning("Coaching generation failed, using fallback: %s", e)
        fallback_id = FALLBACK_MOVES.get(trigger, "slow_down")
        entry = get_move_by_id(fallback_id)
        return entry or COACHING_MOVES[0]


def get_move_by_id(move_id: str) -> dict[str, str] | None:
    for m in COACHING_MOVES:
        if m["move"] == move_id:
            return m
    return None


# --- Whisper audio via Google Cloud Text-to-Speech ---

COACHING_LIVE_AUDIO = os.environ.get("COACHING_LIVE_AUDIO", "0").strip().lower() in ("1", "true", "yes")

_tts_client = None


def _get_tts_client():
    """Build a Google Cloud TTS client (lazy singleton)."""
    global _tts_client
    if _tts_client is not None:
        return _tts_client
    try:
        from google.cloud import texttospeech_v1 as texttospeech
        _tts_client = texttospeech.TextToSpeechAsyncClient()
        return _tts_client
    except ImportError:
        logger.warning("google-cloud-texttospeech not installed; whisper audio disabled")
        return None
    except Exception as e:
        logger.warning("TTS client init failed: %s", e)
        return None


def _apply_whisper_effect(pcm_bytes: bytes) -> bytes:
    """
    Post-process PCM16 audio to sound like a soft whisper.

    Applies only:
    - Low-pass smoothing (reduces sharp harmonics for softer tone)
    - Gentle amplitude reduction (quieter, intimate feel)

    No synthetic noise is added — previous breath noise caused audible
    background static that users found distracting.
    """
    import struct

    num_samples = len(pcm_bytes) // 2
    if num_samples < 2:
        return pcm_bytes

    # Unpack PCM16 samples
    samples = list(struct.unpack(f"<{num_samples}h", pcm_bytes))

    # Pass 1: Low-pass smoothing (averages adjacent samples to soften harmonics)
    smoothed = [samples[0]]
    for i in range(1, num_samples):
        # Weighted average: 40% previous + 60% current — gentle smoothing
        s = int(0.4 * smoothed[i - 1] + 0.6 * samples[i])
        smoothed.append(s)

    # Pass 2: Reduce amplitude for soft whisper feel
    VOICE_GAIN = 0.50  # 50% of original amplitude — soft but clearly audible

    result = []
    for s in smoothed:
        voice = int(s * VOICE_GAIN)
        voice = max(-32768, min(32767, voice))
        result.append(voice)

    return struct.pack(f"<{num_samples}h", *result)


async def _generate_whisper_audio_live(text: str) -> str | None:
    """
    Generate whisper audio via a SHORT-LIVED Gemini Live session.

    Opens a separate Live session (independent of the main transcription session),
    sends the coaching text, collects the audio response, and closes the session.
    This produces natural, human-like speech — the single most visible differentiator
    vs. Cloud TTS or browser Web Speech API.

    Returns base64-encoded PCM16 24kHz mono audio, or None on failure.
    """
    try:
        import asyncio
        from app.gemini_live_client import _make_genai_client

        client = _make_genai_client()
        model = os.environ.get("GEMINI_MODEL", "gemini-live-2.5-flash-native-audio")

        live_config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
            },
            "system_instruction": {
                "parts": [
                    {
                        "text": (
                            "You are Sage, a calm and warm conversation coach. "
                            "Read the following coaching whisper text aloud in a soft, "
                            "gentle, intimate tone — as if whispering encouragement "
                            "in someone's ear. Speak slowly and warmly. "
                            "Say ONLY the exact text provided, nothing more."
                        )
                    }
                ]
            },
        }

        cm = client.aio.live.connect(model=model, config=live_config)
        session = await cm.__aenter__()

        try:
            from google.genai import types

            # Send the coaching text for the model to speak
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=f"Whisper this: {text}")],
                ),
                turn_complete=True,
            )

            # Collect audio chunks with a timeout
            audio_chunks: list[bytes] = []
            try:
                deadline = asyncio.get_event_loop().time() + 8.0
                async for msg in session.receive():
                    # Collect audio from model_turn parts
                    if hasattr(msg, "server_content") and msg.server_content:
                        sc = msg.server_content
                        if hasattr(sc, "model_turn") and sc.model_turn:
                            for part in sc.model_turn.parts:
                                if hasattr(part, "inline_data") and part.inline_data:
                                    audio_chunks.append(part.inline_data.data)
                        # Stop when turn is complete
                        if hasattr(sc, "turn_complete") and sc.turn_complete:
                            break
                    # Manual timeout check
                    if asyncio.get_event_loop().time() > deadline:
                        logger.warning("Gemini Live TTS timed out after 8s")
                        break
            except (asyncio.TimeoutError, StopAsyncIteration):
                pass

            if not audio_chunks:
                logger.warning("Gemini Live TTS returned no audio chunks")
                return None

            audio_bytes = b"".join(audio_chunks)
            audio_bytes = _apply_whisper_effect(audio_bytes)
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            logger.info("Gemini Live TTS whisper generated: %d bytes PCM16 24kHz", len(audio_bytes))
            return b64

        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

    except Exception as e:
        logger.warning("Gemini Live TTS failed (will try Cloud TTS): %s", e)
        return None


async def _generate_whisper_audio_cloud_tts(text: str) -> str | None:
    """
    Generate whisper audio via Google Cloud TTS (fallback for Live TTS).

    Returns base64-encoded PCM16 24kHz mono audio, or None on failure.
    """
    client = _get_tts_client()
    if client is None:
        return None
    try:
        from google.cloud import texttospeech_v1 as texttospeech
        import html as _html
        safe_text = _html.escape(text)

        ssml = (
            '<speak>'
            '<prosody rate="85%" volume="x-soft">'
            f'{safe_text}'
            '</prosody>'
            '</speak>'
        )

        request = texttospeech.SynthesizeSpeechRequest(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Studio-O",
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=0.9,
                pitch=-2.0,
            ),
        )

        response = await client.synthesize_speech(request=request)
        audio_bytes = response.audio_content

        if len(audio_bytes) > 44 and audio_bytes[:4] == b'RIFF':
            audio_bytes = audio_bytes[44:]

        audio_bytes = _apply_whisper_effect(audio_bytes)
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        logger.info("Cloud TTS whisper generated: %d bytes PCM16 24kHz", len(audio_bytes))
        return b64
    except Exception as e:
        logger.warning("Cloud TTS whisper failed: %s", e)
        return None


async def generate_whisper_audio(text: str) -> str | None:
    """
    Generate whisper audio for coaching text.

    Strategy: Try Gemini Live TTS first (natural human-like speech), then
    fall back to Cloud TTS (Studio voice + SSML), then browser Web Speech API
    (handled by frontend when audio_base64 is None).

    Returns base64-encoded PCM16 24kHz mono audio, or None on failure.
    """
    # Try Gemini Live TTS first — most natural sounding
    b64 = await _generate_whisper_audio_live(text)
    if b64:
        return b64

    # Fall back to Cloud TTS
    b64 = await _generate_whisper_audio_cloud_tts(text)
    if b64:
        return b64

    logger.warning("All TTS methods failed for whisper; frontend will use browser Web Speech")
    return None


async def generate_backchannel_audio(text: str) -> str | None:
    """
    Generate short backchannel audio ("Ok.", "I see.") using the same Gemini Live
    TTS voice (Puck) as coaching whispers, so backchannel and whisper share one
    consistent persona. Falls back to Cloud TTS if Live TTS fails.

    Returns base64-encoded PCM16 24kHz mono audio, or None on failure.
    """
    # Try Gemini Live TTS first — same Puck voice as whisper
    b64 = await _generate_whisper_audio_live(text)
    if b64:
        logger.info("Live TTS backchannel generated, text=%s", text)
        return b64

    # Fall back to Cloud TTS
    b64 = await _generate_backchannel_cloud_tts(text)
    if b64:
        return b64

    logger.warning("All backchannel TTS methods failed for: %s", text)
    return None


async def _generate_backchannel_cloud_tts(text: str) -> str | None:
    """Cloud TTS fallback for backchannel audio."""
    client = _get_tts_client()
    if client is None:
        return None
    try:
        from google.cloud import texttospeech_v1 as texttospeech

        import html as _html
        safe_text = _html.escape(text)
        ssml = (
            '<speak>'
            '<prosody rate="85%" volume="x-soft">'
            f'{safe_text}'
            '</prosody>'
            '</speak>'
        )

        request = texttospeech.SynthesizeSpeechRequest(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Studio-O",
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=0.9,
                pitch=-2.0,
            ),
        )

        response = await client.synthesize_speech(request=request)
        audio_bytes = response.audio_content

        # Strip WAV header if present
        if len(audio_bytes) > 44 and audio_bytes[:4] == b'RIFF':
            audio_bytes = audio_bytes[44:]

        # Apply same whisper post-processing (smoothing + amplitude reduction)
        audio_bytes = _apply_whisper_effect(audio_bytes)

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        logger.info("Cloud TTS backchannel generated: %d bytes PCM16 24kHz, text=%s", len(audio_bytes), text)
        return b64
    except Exception as e:
        logger.warning("Cloud TTS backchannel failed: %s", e)
        return None
