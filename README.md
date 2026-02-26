# Transcribation Server

FastAPI server for async audio transcription (RU-focused) with queue-based processing, SQLite, optional Redis cache, and optional Telegram bot.

## Features
- Async job API (`POST /v1/transcriptions`, status/result endpoints)
- API-key authorization via `X-API-Key`
- Audio normalization (`ffmpeg`) and duration checks
- Background processing with GPU concurrency control
- Real GigaAM model integration (`transcribe` + `transcribe_longform`)
- Faster-Whisper backend with the same async API and segment output
- Local-first mode: SQLite database and no required external services
- Ready for integration with Telegram bot backend (`aiogram`) as a separate client service

## Run Locally
```bash
python -m pip install -e .[dev]
copy .env.example .env  # Linux/macOS: cp .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --app-dir src
```

No Docker is required for the default setup.

## GigaAM Setup
Install model package from official repository:
```bash
python -m pip install --user "gigaam @ git+https://github.com/salute-developers/GigaAM.git"
python -m pip install --user "huggingface-hub<1"
python -m pip install --user "pyannote.audio<4"
```

Recommended `.env` values for RTX 3060:
- `ASR_DEVICE=cuda`
- `MODEL_NAME=v3_e2e_ctc` (or `v3_e2e_rnnt`)
- `ASR_FORCE_MOCK=false`

Notes:
- Audio up to 25 seconds uses `transcribe`.
- Audio longer than 25 seconds uses `transcribe_longform`.
- If `gigaam` is not installed or fails to load, service falls back to mock mode (for debug only).
- Keep `torch/torchaudio` in range `<2.9` for `gigaam` compatibility.

## Faster-Whisper Setup
Switch backend in `.env`:
```env
ASR_BACKEND=faster_whisper
FASTER_WHISPER_MODEL=antony66/whisper-large-v3-russian
ASR_DEVICE=cuda
FASTER_WHISPER_COMPUTE_TYPE=float16
FASTER_WHISPER_VAD_FILTER=true
FASTER_WHISPER_TASK=transcribe
```

Notes:
- Same API endpoints (`/v1/transcriptions`, `/v1/jobs/{id}`, `/v1/jobs/{id}/result`).
- Long audio is handled directly by Faster-Whisper (segment stream returned by model).
- If CUDA load fails, engine falls back to CPU `int8` automatically.
- `antony66/whisper-large-v3-russian` is a RU-optimized model and is recommended as default for Russian transcription.
- If HF model is not in CTranslate2 format, server auto-converts it on first start (can take several minutes).

## API Quick Start
```bash
curl -X POST "http://localhost:8000/v1/transcriptions" ^
  -H "X-API-Key: dev-key" ^
  -F "file=@sample.wav"
```

Then:
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/result`
- `GET /v1/jobs/{job_id}/download.txt` (download text file named like source audio)

Full API spec: `docs/api-spec.md`
Windows 11 background/autostart guide: `docs/windows-autostart.md`

## Migrations
```bash
python -m alembic upgrade head
```

## Tests
```bash
python -m pytest -q
```

## Optional Services (without Docker)
- Redis cache/status: set `REDIS_ENABLED=true` and `REDIS_URL=redis://...`
- Install `ffmpeg`/`ffprobe` in system `PATH` for mp3/ogg/m4a normalization

## Telegram Bot (aiogram v3)
Bot can run inside the same FastAPI process and use existing ASR queue/components.

1. Set in `.env`:
```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_PYROGRAM_ENABLED=true
TELEGRAM_API_ID=<your_api_id>
TELEGRAM_API_HASH=<your_api_hash>
TELEGRAM_AUTH_QUESTION=Введите код доступа
TELEGRAM_AUTH_ANSWER=<secret_answer>
```
2. Start API as usual:
```bash
python -m uvicorn app.main:app --reload --app-dir src
```
3. In Telegram:
- `/start` -> answer auth question once
- send audio/voice/file -> receive `.txt` transcript when done
- `/status` -> status of your last task

Important limitation:
- Bot API `getFile` has a hard limit around 20 MB.
- For files larger than 20 MB, enable `pyrogram` (`TELEGRAM_PYROGRAM_ENABLED=true`) with `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`; then download goes via MTProto and large files are supported.
