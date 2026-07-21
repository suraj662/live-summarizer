"""Application configuration loaded from ``backend/.env``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


def _cors_origins(value: str) -> tuple[str, ...]:
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    return origins or ("http://localhost:3000",)


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    firebase_service_account_path: str | None
    firebase_service_account_json: str | None
    whisper_model: str
    whisper_device: str
    whisper_download_root: str
    ollama_base_url: str
    ollama_model: str
    ollama_request_timeout_seconds: int
    audio_sample_rate: int
    audio_buffer_seconds: int

    @property
    def audio_buffer_bytes(self) -> int:
        """Bytes in one buffer of signed 16-bit, mono PCM audio."""
        return self.audio_sample_rate * self.audio_buffer_seconds * 2


@lru_cache
def get_settings() -> Settings:
    return Settings(
        host=os.getenv("HOST", "0.0.0.0"),
        port=_positive_int("PORT", 8000),
        cors_origins=_cors_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000")),
        firebase_service_account_path=os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH") or None,
        firebase_service_account_json=os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or None,
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
        whisper_download_root=os.getenv("WHISPER_DOWNLOAD_ROOT", "./models/whisper"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        ollama_request_timeout_seconds=_positive_int("OLLAMA_REQUEST_TIMEOUT_SECONDS", 120),
        audio_sample_rate=_positive_int("AUDIO_SAMPLE_RATE", 16_000),
        audio_buffer_seconds=_positive_int("AUDIO_BUFFER_SECONDS", 2),
    )


settings = get_settings()
