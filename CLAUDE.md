# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (includes dev extras)
python -m pip install -e .[dev]

# Apply DB migrations
python -m alembic upgrade head

# Run server
python -m uvicorn app.main:app --reload --app-dir src

# Run all tests
python -m pytest -q

# Run a single test file
python -m pytest tests/test_api.py -q

# Lint
python -m ruff check src tests

# Lint + autofix
python -m ruff check --fix src tests
```

`ffmpeg` and `ffprobe` must be in system PATH for audio normalization. Without them, only WAV input works when `TRANSCODE_ENABLED=false`.

## Architecture

The app is a FastAPI server (`src/app/`) with an async job queue for GPU-bound ASR work.

**Request lifecycle (HTTP API):**
1. `POST /v1/transcriptions` → `api/routes.py` saves the upload via `media/processing.py:save_upload`, runs `ffmpeg` normalization, calls `JobManager.enqueue()`, schedules `JobManager._process()` as a FastAPI background task.
2. `_process()` acquires `asyncio.Semaphore(GPU_CONCURRENCY)` before calling `asr_engine.transcribe()` — this is the only GPU concurrency gate.
3. Status/result are written to SQLite (`db/repository.py`) and optionally mirrored to Redis (`storage/redis_cache.py`).

**ASR engines** (`asr/`):
- `AsrEngine` — abstract base with `warmup()` + `transcribe()`.
- `GigaAMEngine` — wraps GigaAM. Audio ≤25 s → `model.transcribe()`; >25 s → `model.transcribe_longform()` (needs `pyannote.audio` + `huggingface_hub`). On Windows, `HFValidationError` from huggingface_hub 1.x triggers a chunked short-form fallback. Falls back to mock if import fails.
- `FasterWhisperEngine` — wraps `faster-whisper`. CUDA load failure falls back to CPU `int8` automatically.
- `build_asr_engine(settings)` in `asr/factory.py` selects the engine from `ASR_BACKEND`.

**Telegram bot** (`bot/`):
- Runs inside the same FastAPI process, started in `main.py:lifespan` when `TELEGRAM_ENABLED=true`.
- `handlers.py` receives aiogram messages. Files >20 MB are blocked unless `service.can_download_large_files()` returns `True` (requires all four: `TELEGRAM_PYROGRAM_ENABLED=true`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`).
- `service.py:_download_file_with_fallback()` tries Pyrogram first; falls back to Bot API only if the file is ≤20 MB (otherwise raises `MediaProcessingError` with the real Pyrogram exception).
- After enqueue, `schedule_result_delivery()` polls the DB in a detached `asyncio.Task` and sends the `.txt` file via `bot.send_document` when done.

**Settings** (`core/config.py`):
- All config via `pydantic-settings` from `.env`. `get_settings()` is `@lru_cache` — call `get_settings.cache_clear()` in tests before creating the app.
- Key limits: `MAX_FILE_MB` (default 200), `MAX_DURATION_SEC` (default 7200), `MAX_QUEUE_SIZE` (default 100), `GPU_CONCURRENCY` (default 1).

**Database** (`db/`):
- SQLAlchemy async + aiosqlite. Two models: `Job` and `Transcript` (one-to-one), plus `TelegramUser`.
- `auto_create_tables=true` (default) calls `init_db()` on startup; Alembic is the proper migration tool for schema changes.

**Tests** (`tests/`):
- `conftest.py` uses `TestClient` with an in-memory SQLite DB, `REDIS_ENABLED=false`, `TRANSCODE_ENABLED=false`, and `API_KEYS=test-key`. Must clear `get_settings` cache before and after each test fixture.
- ASR is auto-mocked via `ASR_FORCE_MOCK` or because gigaam/faster-whisper is not installed in CI.
