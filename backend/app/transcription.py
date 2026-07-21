"""Local OpenAI Whisper transcription for 16-bit PCM meeting audio."""

from __future__ import annotations

import math
import threading
from functools import lru_cache
from typing import Any

import numpy as np
import whisper
from whisper.audio import SAMPLE_RATE as WHISPER_SAMPLE_RATE

from app.config import settings


# Whisper/PyTorch inference should not be invoked concurrently against one model
# instance, particularly when the model is running on a GPU.
_transcription_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_whisper_model() -> Any:
    """Load the configured Whisper model once per Python process."""
    return whisper.load_model(
        settings.whisper_model,
        device=settings.whisper_device,
        download_root=settings.whisper_download_root,
    )


def _resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
    """Resample an in-memory waveform to Whisper's required 16 kHz rate."""
    if source_rate == WHISPER_SAMPLE_RATE:
        return audio

    target_length = round(len(audio) * WHISPER_SAMPLE_RATE / source_rate)
    if target_length <= 0:
        return np.empty(0, dtype=np.float32)

    source_positions = np.arange(len(audio), dtype=np.float32)
    target_positions = np.linspace(0, len(audio) - 1, target_length, dtype=np.float32)
    return np.interp(target_positions, source_positions, audio).astype(np.float32)


def _confidence(result: dict[str, Any]) -> float | None:
    """Convert Whisper segment log probabilities into an average 0–1 confidence."""
    probabilities: list[float] = []
    for segment in result.get("segments", []):
        average_log_probability = segment.get("avg_logprob")
        if isinstance(average_log_probability, (float, int)):
            probabilities.append(min(1.0, math.exp(float(average_log_probability))))

    return sum(probabilities) / len(probabilities) if probabilities else None


def transcribe_audio(
    audio_bytes: bytes, sample_rate: int = WHISPER_SAMPLE_RATE
) -> tuple[str, float | None]:
    """Transcribe signed 16-bit mono PCM bytes and return ``(text, confidence)``."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than zero")
    if len(audio_bytes) % 2:
        raise ValueError("PCM audio must contain whole 16-bit samples")
    if not audio_bytes:
        return "", None

    audio = np.frombuffer(audio_bytes, dtype="<i2").astype(np.float32) / 32768.0
    audio = _resample(audio, sample_rate)
    if not len(audio):
        return "", None

    with _transcription_lock:
        result = get_whisper_model().transcribe(
            audio,
            fp16=settings.whisper_device != "cpu",
        )

    return str(result.get("text", "")).strip(), _confidence(result)
