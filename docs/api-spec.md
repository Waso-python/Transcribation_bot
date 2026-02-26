# API Specification

Base URL (local): `http://127.0.0.1:8000`

All `v1` endpoints require API key header:
- Header: `X-API-Key: <key>`
- On auth failure: `401 {"detail":"Invalid API key"}`

## Authentication

### API key
- Source: environment variable `API_KEYS`
- Format: comma-separated list, for example: `API_KEYS=dev-key,prod-key`

## Common Models

### JobStatus
- `queued`
- `processing`
- `done`
- `failed`

### Segment
```json
{
  "start": 0.0,
  "end": 1.2,
  "text": "..."
}
```

## Endpoints

### 1) Create transcription job
`POST /v1/transcriptions`

Content type: `multipart/form-data`
- field `file`: audio file

Supported extensions:
- `.wav`, `.mp3`, `.ogg`, `.m4a`

Success:
- `202 Accepted`
```json
{
  "job_id": "9f0b0af6-8d95-4f89-a2d9-d2f5304de8e1",
  "status": "queued",
  "created_at": "2026-02-20T18:00:00.123456Z",
  "eta_seconds": null
}
```

Errors:
- `400` unsupported format / transcode / probe errors / audio too long
- `401` invalid API key
- `413` uploaded file exceeds configured size limit
- `429` queue overloaded

Example:
```bash
curl -X POST "http://127.0.0.1:8000/v1/transcriptions" \
  -H "X-API-Key: dev-key" \
  -F "file=@sample.wav"
```

### 2) Get job status
`GET /v1/jobs/{job_id}`

Success:
- `200 OK`
```json
{
  "job_id": "9f0b0af6-8d95-4f89-a2d9-d2f5304de8e1",
  "status": "processing",
  "progress": 10,
  "duration_sec": 34.8,
  "error_code": null,
  "error_message": null
}
```

Errors:
- `401` invalid API key
- `404` job not found

### 3) Get transcription result (JSON)
`GET /v1/jobs/{job_id}/result`

Success:
- `200 OK`
```json
{
  "job_id": "9f0b0af6-8d95-4f89-a2d9-d2f5304de8e1",
  "language": "ru",
  "model": "antony66/whisper-large-v3-russian",
  "text": "Полный текст расшифровки",
  "segments": [
    {
      "start": 0.0,
      "end": 1.2,
      "text": "Привет"
    }
  ],
  "audio_duration_sec": 34.8,
  "processing_time_sec": 12.4
}
```

Errors:
- `401` invalid API key
- `404` job not found
- `409` job not finished
- `500` result missing in DB

### 4) Download transcription as TXT
`GET /v1/jobs/{job_id}/download.txt`

Success:
- `200 OK`
- `Content-Type: text/plain; charset=utf-8`
- `Content-Disposition: attachment; filename=...`

Errors:
- `401` invalid API key
- `404` job not found
- `409` job not finished
- `500` result missing in DB

### 5) Liveness probe
`GET /health/live`

Success:
- `200 OK`
```json
{"status":"ok"}
```

### 6) Readiness probe
`GET /health/ready`

Success:
- `200 OK`
```json
{"status":"ready"}
```

Errors:
- `503` database unavailable
- `503` redis unavailable (when enabled)
- `503` ASR model unavailable

## Async Workflow
1. Upload audio via `POST /v1/transcriptions`.
2. Poll `GET /v1/jobs/{job_id}` until status is `done` or `failed`.
3. Fetch result via `GET /v1/jobs/{job_id}/result` or download TXT via `GET /v1/jobs/{job_id}/download.txt`.

## Telegram Bot Notes
- Bot can submit files to the same internal pipeline.
- Bot API file download has size limit (about 20 MB via `getFile`).
- To handle larger files, enable MTProto download via `pyrogram` (`TELEGRAM_PYROGRAM_ENABLED=true`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`).
