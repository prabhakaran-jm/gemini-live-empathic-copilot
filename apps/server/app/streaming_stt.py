"""
Real-time transcription via Google Cloud Speech-to-Text streaming API.
Used when Gemini Live does not deliver input_audio_transcription (receive yields 0).
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Optional: only used when LIVE_STT_STREAMING=1 and google-cloud-speech is installed
_SpeechClient: Any = None
_StreamingRecognizeRequest: Any = None
_StreamingRecognitionConfig: Any = None
_RecognitionConfig: Any = None
_AudioEncoding: Any = None


def _ensure_speech_client() -> bool:
    global _SpeechClient, _StreamingRecognizeRequest, _StreamingRecognitionConfig, _RecognitionConfig, _AudioEncoding
    if _SpeechClient is not None:
        return True
    try:
        from google.cloud import speech

        _SpeechClient = speech.SpeechClient  # type: ignore[assignment]
        _StreamingRecognizeRequest = speech.StreamingRecognizeRequest  # type: ignore[assignment]
        _StreamingRecognitionConfig = speech.StreamingRecognitionConfig  # type: ignore[assignment]
        _RecognitionConfig = speech.RecognitionConfig  # type: ignore[assignment]
        _AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16  # type: ignore[assignment]
        return True
    except Exception as e:
        logger.debug("streaming_stt: google-cloud-speech not available: %s", e)
        return False


def _audio_request_generator(audio_queue: queue.Queue[bytes | None]) -> Any:
    """Yield StreamingRecognizeRequest from queue; stop when None is received."""
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            return
        if chunk:
            yield _StreamingRecognizeRequest(audio_content=chunk)


def run_streaming_stt(
    audio_queue: queue.Queue[bytes | None],
    result_queue: queue.Queue[tuple[str | None, bool]],
    sample_rate_hz: int = 16000,
    language_code: str = "en-US",
) -> None:
    """
    Run in a dedicated thread. Consume PCM chunks from audio_queue,
    stream to Speech-to-Text, push (transcript, is_final) to result_queue.
    Put None in audio_queue to stop; then (None, False) is put in result_queue.
    """
    if not _ensure_speech_client():
        result_queue.put((None, False))
        return
    try:
        client = _SpeechClient()
        config = _RecognitionConfig(
            encoding=_AudioEncoding,
            sample_rate_hertz=sample_rate_hz,
            language_code=language_code,
        )
        streaming_config = _StreamingRecognitionConfig(config=config, interim_results=True)
        responses = client.streaming_recognize(
            streaming_config, _audio_request_generator(audio_queue)
        )
        for response in responses:
            if not response.results:
                continue
            result = response.results[0]
            if not result.alternatives:
                continue
            transcript = result.alternatives[0].transcript.strip()
            if transcript:
                result_queue.put((transcript, result.is_final))
    except Exception as e:
        logger.warning("Streaming STT error: %s", e)
    finally:
        result_queue.put((None, False))


def start_streaming_stt_thread(
    sample_rate_hz: int = 16000,
    language_code: str = "en-US",
) -> tuple[threading.Thread, queue.Queue[bytes | None], queue.Queue[tuple[str | None, bool]]] | None:
    """
    Start the streaming STT thread. Returns (thread, audio_queue, result_queue)
    or None if Speech-to-Text is unavailable.
    """
    if not _ensure_speech_client():
        return None
    # Bounded so we drop audio if the recognizer falls behind (avoids unbounded memory).
    audio_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=128)
    result_queue: queue.Queue[tuple[str | None, bool]] = queue.Queue()
    thread = threading.Thread(
        target=run_streaming_stt,
        args=(audio_queue, result_queue),
        kwargs={"sample_rate_hz": sample_rate_hz, "language_code": language_code},
        daemon=True,
    )
    thread.start()
    return (thread, audio_queue, result_queue)
