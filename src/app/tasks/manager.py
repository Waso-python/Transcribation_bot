import asyncio
import logging
import time
from pathlib import Path

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.asr.engine import AsrEngine
from app.core.config import Settings
from app.db.models import Job, JobStatus
from app.db.repository import JobRepository
from app.media.processing import cleanup_file
from app.storage.redis_cache import RedisCache

logger = logging.getLogger(__name__)


class QueueFullError(RuntimeError):
    pass


class JobManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker,
        asr_engine: AsrEngine,
        cache: RedisCache,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.asr_engine = asr_engine
        self.cache = cache
        self._semaphore = asyncio.Semaphore(settings.gpu_concurrency)
        self._queue_lock = asyncio.Lock()
        self._queued_count = 0

    async def enqueue(
        self,
        source_file_path: Path,
        normalized_path: Path,
        original_filename: str | None,
        duration_sec: float,
        language: str,
    ) -> Job:
        async with self._queue_lock:
            if self._queued_count >= self.settings.max_queue_size:
                raise QueueFullError("Queue is full")
            self._queued_count += 1

        async with self.session_factory() as session:
            repo = JobRepository(session)
            job = await repo.create_job(
                file_path=str(source_file_path),
                normalized_path=str(normalized_path),
                original_filename=original_filename,
                model_name=self.settings.effective_model_name,
                language=language,
                duration_sec=duration_sec,
            )
            await self.cache.set_job_status(
                job.id,
                {"status": JobStatus.QUEUED, "progress": 0},
            )
        return job

    def schedule(self, background_tasks: BackgroundTasks, job_id: str) -> None:
        background_tasks.add_task(self._process, job_id)

    def schedule_detached(self, job_id: str) -> asyncio.Task:
        return asyncio.create_task(self._process(job_id))

    async def _process(self, job_id: str) -> None:
        started = time.perf_counter()
        normalized_path: Path | None = None
        source_path: Path | None = None
        try:
            async with self.session_factory() as session:
                repo = JobRepository(session)
                job = await repo.get_job(job_id)
                if job is None:
                    return
                normalized_path = Path(job.normalized_path)
                source_path = Path(job.file_path)
                await repo.set_status(job_id, JobStatus.PROCESSING, progress=10)
                await self.cache.set_job_status(job_id, {"status": JobStatus.PROCESSING, "progress": 10})

            async with self._semaphore:
                asr_result = await self.asr_engine.transcribe(
                    str(normalized_path),
                    punctuation=self.settings.punctuation_default,
                )

            processing_time = time.perf_counter() - started
            segments_payload = [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in asr_result.segments
            ]
            async with self.session_factory() as session:
                repo = JobRepository(session)
                await repo.save_transcript(
                    job_id=job_id,
                    text=asr_result.text,
                    segments=segments_payload,
                    language=asr_result.language,
                    processing_time_sec=processing_time,
                )
                await repo.set_status(job_id, JobStatus.DONE, progress=100)
                await self.cache.set_job_status(job_id, {"status": JobStatus.DONE, "progress": 100})
        except Exception as exc:
            logger.exception("Job failed: %s", job_id)
            async with self.session_factory() as session:
                repo = JobRepository(session)
                await repo.set_status(
                    job_id,
                    JobStatus.FAILED,
                    progress=100,
                    error_code="ASR_FAILED",
                    error_message=str(exc),
                )
            await self.cache.set_job_status(
                job_id,
                {"status": JobStatus.FAILED, "progress": 100, "error_code": "ASR_FAILED"},
            )
        finally:
            async with self._queue_lock:
                self._queued_count = max(0, self._queued_count - 1)
            if self.settings.cleanup_files:
                if normalized_path is not None:
                    cleanup_file(normalized_path)
                if source_path is not None and source_path != normalized_path:
                    cleanup_file(source_path)
