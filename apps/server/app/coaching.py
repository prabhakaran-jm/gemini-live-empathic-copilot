"""
Coaching moves: deterministic triggers + Gemini-generated contextual whispers.
Falls back to fixed 8-12 word phrases if generation fails.
Grounded in Nonviolent Communication (NVC) and active listening principles.
Optional: Google Search grounding (COACHING_GROUNDING=1) and vision (image_base64) for context.
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

# When set (e.g. "1", "true"), coaching generation uses Google Search grounding for citations.
COACHING_GROUNDING = os.environ.get("COACHING_GROUNDING", "").lower() in ("1", "true", "yes")

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
- Keep it short: about 8–12 words preferred; accept 5–25 words
- Use NVC principles: observations, feelings, needs, requests
- Use active listening: reflect, validate, invite perspective
- Never diagnose, label, or judge either party
- Speak directly to the user in second person ("you")
- Be warm, gentle, and concise — like a whisper in their ear
- Output ONLY the whisper phrase, nothing else

Trigger types:
- tension_cross: tension just rose above the threshold (default 24/100; conversation heating up)
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
            location=os.environ.get("GOOGLE_CLOUD_REGION", "europe-west1"),
        )
    else:
        _flash_client = genai.Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            location=os.environ.get("GOOGLE_CLOUD_REGION", "europe-west1"),
        )
    return _flash_client


def _build_grounding_tools():
    """Return tools list for Google Search grounding when COACHING_GROUNDING is enabled."""
    if not COACHING_GROUNDING:
        return []
    try:
        from google.genai import types
        return [types.Tool(google_search=types.GoogleSearch())]
    except Exception as e:
        logger.warning("Google Search grounding not available: %s", e)
        return []


async def generate_coaching(
    trigger: str,
    tension_score: int,
    transcript_buffer: str,
    image_base64: str | None = None,
) -> dict[str, str]:
    """
    Call gemini-2.0-flash to produce a contextual coaching whisper.
    Returns {"move": trigger, "text": "..."}.
    Falls back to fixed phrase on any failure.
    When image_base64 is provided (e.g. from webcam), it is used as visual context for the whisper.
    """
    try:
        from google import genai
        from google.genai import types

        client = _get_flash_client()
        user_prompt = (
            f"Trigger: {trigger}\n"
            f"Current tension: {tension_score}/100\n"
            f"Recent transcript:\n{transcript_buffer[-500:]}\n\n"
            f"Generate one coaching whisper (8-12 words):"
        )
        config_kw: dict = {
            "system_instruction": COACHING_SYSTEM_PROMPT,
            "max_output_tokens": 30,
            "temperature": 0.7,
        }
        tools = _build_grounding_tools()
        if tools:
            config_kw["tools"] = tools

        if image_base64:
            try:
                raw = base64.b64decode(image_base64, validate=True)
                content = types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=raw, mime_type="image/jpeg"),
                        types.Part.from_text(text=user_prompt),
                    ],
                )
                contents_arg: types.Content | str = content
            except Exception as e:
                logger.debug("Ignoring invalid image_base64: %s", e)
                contents_arg = user_prompt
        else:
            contents_arg = user_prompt

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents_arg,
            config=genai.types.GenerateContentConfig(**config_kw),
        )
        text = response.text.strip().strip('"').strip("'")
        word_count = len(text.split())
        if word_count < 5 or word_count > 25:
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
