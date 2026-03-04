"""
Real-time transcription via Google Cloud Speech-to-Text streaming API.
Used when Gemini Live does not deliver input_audio_transcription (receive yields 0).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
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


def _audio_only_generator(
    audio_queue: queue.Queue[bytes | None],
    chunk_counter: list[int],
) -> Any:
    """Yield StreamingRecognizeRequest with audio_content only (no config). For v2 API."""
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            return
        if chunk:
            chunk_counter[0] += 1
            yield _StreamingRecognizeRequest(audio_content=chunk)


def _audio_request_generator_legacy(
    audio_queue: queue.Queue[bytes | None],
    streaming_config: Any,
    chunk_counter: list[int],
) -> Any:
    """Yield StreamingRecognizeRequest starting with config, then audio chunks. For v1 API."""
    yield _StreamingRecognizeRequest(streaming_config=streaming_config)
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            return
        if chunk:
            chunk_counter[0] += 1
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

    chunk_counter = [0]
    response_counter = 0
    start_ts = time.time()

    try:
        client = _SpeechClient()
        config = _RecognitionConfig(
            encoding=_AudioEncoding,
            sample_rate_hertz=sample_rate_hz,
            language_code=language_code,
        )
        streaming_config = _StreamingRecognitionConfig(config=config, interim_results=True)

        # SpeechHelpers.streaming_recognize expects (config, requests).
        # The requests iterable should yield StreamingRecognizeRequest(audio_content=...) only.
        requests = _audio_only_generator(audio_queue, chunk_counter)
        try:
            responses = client.streaming_recognize(config=streaming_config, requests=requests)
        except TypeError as e:
            # Legacy API: config inside the first request.
            logger.info("Streaming STT falling back to legacy API: %s", e)
            requests = _audio_request_generator_legacy(audio_queue, streaming_config, chunk_counter)
            responses = client.streaming_recognize(requests=requests)

        logger.info(
            "Streaming STT stream established (elapsed=%.1fs, chunks_queued=%d)",
            time.time() - start_ts,
            chunk_counter[0],
        )

        for response in responses:
            response_counter += 1
            if response_counter <= 5 or response_counter % 20 == 0:
                n_results = len(response.results) if response.results else 0
                detail = ""
                if response.results:
                    r0 = response.results[0]
                    n_alts = len(r0.alternatives) if r0.alternatives else 0
                    alt0_text = r0.alternatives[0].transcript[:80] if n_alts > 0 else "(no alts)"
                    detail = f", alts={n_alts}, is_final={r0.is_final}, text='{alt0_text}'"
                logger.info(
                    "STT response #%d: results=%d%s, chunks_sent=%d",
                    response_counter,
                    n_results,
                    detail,
                    chunk_counter[0],
                )
            if not response.results:
                continue
            result = response.results[0]
            if not result.alternatives:
                continue
            transcript = result.alternatives[0].transcript.strip()
            if transcript:
                logger.info(
                    "STT transcript (is_final=%s): %s",
                    result.is_final,
                    transcript[:120],
                )
                result_queue.put((transcript, result.is_final))
    except Exception as e:
        logger.warning(
            "Streaming STT error after %.1fs, %d chunks sent, %d responses: %s",
            time.time() - start_ts,
            chunk_counter[0],
            response_counter,
            e,
        )
    finally:
        logger.info(
            "Streaming STT thread exiting: %.1fs elapsed, %d chunks sent, %d responses received",
            time.time() - start_ts,
            chunk_counter[0],
            response_counter,
        )
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
