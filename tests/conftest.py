import io
import sys
from pathlib import Path
import wave
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.setenv("TRANSCODE_ENABLED", "false")
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "audio"))

    # Ensure settings cache is rebuilt with test env.
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


def build_wav_bytes(seconds: int = 1, sample_rate: int = 16000) -> bytes:
    frames = b"\x00\x00" * seconds * sample_rate
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    return stream.getvalue()
