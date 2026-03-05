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
You are an invisible real-time conversation coach using Nonviolent Communication (NVC) \
and active listening. The user is in a difficult conversation right now. Based on the \
transcript, tension level, trigger, and optionally their webcam image, generate ONE coaching whisper.

Rules:
- Exactly 8 to 12 words, no more
- Use NVC principles: observations, feelings, needs, requests
- Use active listening: reflect, validate, invite perspective
- Never diagnose, label, or judge either party
- Speak directly to the user in second person ("you")
- Be warm, gentle, and concise — like a whisper in their ear
- If a webcam image is provided, you may reference visible body language cues \
(e.g. tension, posture, facial expression) to make coaching more relevant
- Output ONLY the whisper phrase, nothing else

Trigger types:
- tension_cross: tension just rose above 40/100 (conversation heating up)
- barge_in: 2+ interruptions detected (turn-taking friction, people talking over each other)
- post_escalation_silence: awkward silence after high tension (pause after escalation)\
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


async def generate_whisper_audio(text: str) -> str | None:
    """
    Generate whisper-quality audio from coaching text using Google Cloud TTS
    + post-processing for a breathy, airy whisper effect.

    Returns base64-encoded PCM16 24kHz mono audio, or None on failure.
    The frontend plays this via playWhisperAudio() at gain 0.12.
    """
    if not COACHING_LIVE_AUDIO:
        return None
    client = _get_tts_client()
    if client is None:
        return None
    try:
        from google.cloud import texttospeech_v1 as texttospeech

        # SSML with soft prosody: slow, quiet
        ssml = (
            '<speak>'
            '<prosody rate="slow" pitch="-1st" volume="x-soft">'
            f'{text}'
            '</prosody>'
            '</speak>'
        )

        request = texttospeech.SynthesizeSpeechRequest(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Neural2-F",  # Soft female neural voice
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,  # Matches playWhisperAudio() on frontend
                speaking_rate=0.9,
                pitch=-2.0,
            ),
        )

        response = await client.synthesize_speech(request=request)
        audio_bytes = response.audio_content

        # Cloud TTS LINEAR16 includes a 44-byte WAV header; strip it for raw PCM
        if len(audio_bytes) > 44 and audio_bytes[:4] == b'RIFF':
            audio_bytes = audio_bytes[44:]

        # Apply whisper post-processing: smoothing + breath noise + amplitude reduction
        audio_bytes = _apply_whisper_effect(audio_bytes)

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        logger.info("TTS whisper audio generated+processed: %d bytes PCM16 24kHz", len(audio_bytes))
        return b64
    except Exception as e:
        logger.warning("TTS whisper audio generation failed (will use browser TTS fallback): %s", e)
        return None


async def generate_backchannel_audio(text: str) -> str | None:
    """
    Generate short backchannel audio ("Ok.", "Mm-hmm.", "I see.") using
    Google Cloud TTS. Returns base64-encoded PCM16 24kHz mono audio.

    Uses natural speaking voice (no whisper effect) at moderate volume so
    it sounds like a conversational acknowledgement.
    """
    client = _get_tts_client()
    if client is None:
        return None
    try:
        from google.cloud import texttospeech_v1 as texttospeech

        request = texttospeech.SynthesizeSpeechRequest(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Neural2-F",  # Same voice as whisper for consistency
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=1.0,
                pitch=-1.0,  # Slightly lower pitch for warmth
            ),
        )

        response = await client.synthesize_speech(request=request)
        audio_bytes = response.audio_content

        # Strip WAV header if present
        if len(audio_bytes) > 44 and audio_bytes[:4] == b'RIFF':
            audio_bytes = audio_bytes[44:]

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        logger.info("TTS backchannel audio generated: %d bytes PCM16 24kHz, text=%s", len(audio_bytes), text)
        return b64
    except Exception as e:
        logger.warning("TTS backchannel audio generation failed: %s", e)
        return None
