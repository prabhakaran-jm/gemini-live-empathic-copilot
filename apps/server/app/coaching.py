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
transcript, tension level, and trigger, generate ONE coaching whisper.

Rules:
- Exactly 8 to 12 words, no more
- Use NVC principles: observations, feelings, needs, requests
- Use active listening: reflect, validate, invite perspective
- Never diagnose, label, or judge either party
- Speak directly to the user in second person ("you")
- Be warm, gentle, and concise — like a whisper in their ear
- Output ONLY the whisper phrase, nothing else

Trigger types:
- tension_cross: tension just rose above 40/100 (conversation heating up)
- barge_in: 2+ interruptions detected (turn-taking friction, people talking over each other)
- post_escalation_silence: awkward silence after high tension (pause after escalation)\
"""

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
) -> dict[str, str]:
    """
    Call gemini-2.0-flash to produce a contextual coaching whisper.
    Returns {"move": trigger, "text": "..."}.
    Falls back to fixed phrase on any failure.
    """
    try:
        from google import genai

        client = _get_flash_client()
        avoid_line = ""
        if last_whisper:
            avoid_line = f"\nPrevious whisper (DO NOT repeat): \"{last_whisper}\"\n"
        user_prompt = (
            f"Trigger: {trigger}\n"
            f"Current tension: {tension_score}/100\n"
            f"Recent transcript:\n{transcript_buffer[-500:]}\n"
            f"{avoid_line}\n"
            f"Generate one coaching whisper (8-12 words):"
        )
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=COACHING_SYSTEM_PROMPT,
                max_output_tokens=30,
                temperature=0.7,
            ),
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
    Post-process PCM16 audio to sound like real whispering.

    Real whispers differ from normal speech in three key ways:
    1. Breathy/airy — turbulent airflow noise mixed with voice
    2. No strong vocal harmonics — smoothed signal (low-pass effect)
    3. Quieter overall amplitude

    This applies:
    - 40% amplitude reduction (voice becomes quieter)
    - Simple low-pass smoothing (reduces sharp harmonics)
    - Light breath noise mixed in (adds airy/breathy quality)
    """
    import random
    import struct

    num_samples = len(pcm_bytes) // 2
    if num_samples < 2:
        return pcm_bytes

    # Unpack PCM16 samples
    samples = list(struct.unpack(f"<{num_samples}h", pcm_bytes))

    # Seed for reproducible noise
    rng = random.Random(42)

    # Pass 1: Simple low-pass smoothing (averages adjacent samples to soften harmonics)
    smoothed = [samples[0]]
    for i in range(1, num_samples):
        # Weighted average: 40% previous + 60% current — gentle smoothing
        s = int(0.4 * smoothed[i - 1] + 0.6 * samples[i])
        smoothed.append(s)

    # Pass 2: Reduce amplitude + mix in breath noise
    VOICE_GAIN = 0.35  # 35% of original voice amplitude
    NOISE_GAIN = 800   # Breath noise amplitude (out of 32768)

    result = []
    for s in smoothed:
        # Scale down the voice
        voice = int(s * VOICE_GAIN)
        # Add breathy noise (shaped by voice envelope for natural feel)
        # Noise is louder when voice is active, quieter during silence
        envelope = min(1.0, abs(s) / 8000.0)  # 0.0 in silence, 1.0 when speaking
        noise = int(rng.gauss(0, NOISE_GAIN) * (0.3 + 0.7 * envelope))
        mixed = voice + noise
        # Clamp to int16 range
        mixed = max(-32768, min(32767, mixed))
        result.append(mixed)

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
