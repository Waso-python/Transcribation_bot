import json
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.models import JobStatus
from app.db.repository import JobRepository
from app.db.session import ping_db
from app.dependencies import get_db_session, get_job_manager
from app.media.processing import (
    MediaProcessingError,
    audio_duration_seconds,
    cleanup_file,
    normalize_audio,
    save_upload,
)
from app.schemas.jobs import (
    JobCreateResponse,
    JobResultResponse,
    JobStatusResponse,
    JobStatusValue,
    SegmentSchema,
)
from app.tasks.manager import JobManager, QueueFullError

router = APIRouter()


@router.post(
    "/v1/transcriptions",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def create_transcription_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    manager: JobManager = Depends(get_job_manager),
) -> JobCreateResponse:
    source_path = None
    normalized_path = None
    try:
        source_path = await save_upload(file, settings.temp_path, settings.max_file_bytes)
        normalized_path = normalize_audio(source_path, settings)
        duration = audio_duration_seconds(normalized_path)
    except MediaProcessingError as exc:
        if normalized_path is not None:
            cleanup_file(normalized_path)
        if source_path is not None and source_path != normalized_path:
            cleanup_file(source_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if duration > settings.max_duration_sec:
        cleanup_file(normalized_path)
        if source_path != normalized_path:
            cleanup_file(source_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audio too long. Max duration is {settings.max_duration_sec} seconds",
        )

    try:
        job = await manager.enqueue(
            source_file_path=source_path,
            normalized_path=normalized_path,
            original_filename=file.filename,
            duration_sec=duration,
            language=settings.language_default,
        )
        manager.schedule(background_tasks, job.id)
    except QueueFullError as exc:
        cleanup_file(normalized_path)
        if source_path != normalized_path:
            cleanup_file(source_path)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Queue is overloaded, retry later",
        ) from exc

    return JobCreateResponse(
        job_id=job.id,
        status=JobStatusValue.QUEUED,
        created_at=job.created_at,
        eta_seconds=None,
    )


@router.get(
    "/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> JobStatusResponse:
    repo = JobRepository(session)
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=JobStatusValue(job.status),
        progress=job.progress,
        duration_sec=job.audio_duration_sec,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@router.get(
    "/v1/jobs/{job_id}/result",
    response_model=JobResultResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_job_result(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> JobResultResponse:
    repo = JobRepository(session)
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not finished")
    if job.transcript is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Result not found")

    segments = [SegmentSchema(**seg) for seg in json.loads(job.transcript.segments_json)]
    return JobResultResponse(
        job_id=job.id,
        language=job.transcript.language,
        model=job.model_name,
        text=job.transcript.text,
        segments=segments,
        audio_duration_sec=job.audio_duration_sec,
        processing_time_sec=job.transcript.processing_time_sec,
    )


@router.get(
    "/v1/jobs/{job_id}/download.txt",
    dependencies=[Depends(require_api_key)],
)
async def download_job_result_txt(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    repo = JobRepository(session)
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not finished")
    if job.transcript is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Result not found")

    source_name = job.original_filename or Path(job.file_path).name
    file_stem = _safe_stem(source_name)
    txt_name = f"{file_stem}.txt"
    ascii_name = _ascii_filename(txt_name)
    quoted = quote(txt_name)
    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
        )
    }
    return Response(content=job.transcript.text, media_type="text/plain; charset=utf-8", headers=headers)


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> dict[str, str]:
    db_ok = await ping_db()
    if not db_ok:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    cache_ok = await request.app.state.cache.ping()
    if not cache_ok:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis unavailable")
    if not request.app.state.asr_engine.ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Model unavailable")
    return {"status": "ready"}


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "transcript"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", stem).strip().strip(".")
    return cleaned or "transcript"


def _ascii_filename(filename: str) -> str:
    ascii_only = filename.encode("ascii", "ignore").decode("ascii")
    ascii_only = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_only).strip("._")
    return ascii_only or "transcript.txt"
