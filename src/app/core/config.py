from functools import lru_cache
from pathlib import Path
from typing import Literal

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transcribation Server"
    environment: str = "development"
    api_prefix: str = "/v1"

    api_keys: str = "dev-key"

    database_url: str = "sqlite+aiosqlite:///./app.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    asr_backend: Literal["gigaam", "faster_whisper"] = "gigaam"
    model_name: str = "v3_e2e_ctc"
    language_default: str = "ru"
    punctuation_default: bool = True
    asr_force_mock: bool = False
    asr_device: str | None = None
    gigaam_use_flash: bool = False
    gigaam_download_root: str | None = None
    faster_whisper_model: str = "antony66/whisper-large-v3-russian"
    faster_whisper_compute_type: str = "float16"
    faster_whisper_beam_size: int = 5
    faster_whisper_vad_filter: bool = True
    faster_whisper_task: Literal["transcribe", "translate"] = "transcribe"
    faster_whisper_download_root: str | None = None
    hf_token: str | None = None

    max_file_mb: int = 200
    max_duration_sec: int = 7200
    max_queue_size: int = 100
    gpu_concurrency: int = 1

    transcode_enabled: bool = True
    auto_create_tables: bool = True
    temp_dir: str = "./tmp/audio"
    cleanup_files: bool = True

    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_pyrogram_enabled: bool = False
    telegram_pyrogram_session_name: str = "transcribation_bot"
    telegram_auth_question: str = "Введите код доступа"
    telegram_auth_answer: str = "letmein"
    telegram_status_poll_interval_sec: float = 2.0
    telegram_result_wait_timeout_sec: int = 10800

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                    if isinstance(decoded, list):
                        return ",".join(str(item).strip() for item in decoded if str(item).strip())
                except Exception:
                    pass
            return stripped
        return "dev-key"

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def api_key_list(self) -> list[str]:
        return [item.strip() for item in self.api_keys.split(",") if item.strip()]

    @property
    def temp_path(self) -> Path:
        return Path(self.temp_dir)

    @property
    def effective_model_name(self) -> str:
        if self.asr_backend == "faster_whisper":
            return self.faster_whisper_model
        return self.model_name


@lru_cache
def get_settings() -> Settings:
    return Settings()
