import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Job, JobStatus, TelegramUser, Transcript


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(
        self,
        file_path: str,
        normalized_path: str,
        original_filename: str | None,
        model_name: str,
        language: str,
        duration_sec: float | None,
    ) -> Job:
        job = Job(
            file_path=file_path,
            normalized_path=normalized_path,
            original_filename=original_filename,
            model_name=model_name,
            language=language,
            audio_duration_sec=duration_sec,
            status=JobStatus.QUEUED,
            progress=0,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_job(self, job_id: str) -> Job | None:
        stmt = select(Job).where(Job.id == job_id).options(selectinload(Job.transcript))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return

        job.status = status
        if progress is not None:
            job.progress = progress
        if status == JobStatus.PROCESSING:
            job.started_at = datetime.now(timezone.utc)
        if status in (JobStatus.DONE, JobStatus.FAILED):
            job.finished_at = datetime.now(timezone.utc)
        job.error_code = error_code
        job.error_message = error_message
        await self.session.commit()

    async def save_transcript(
        self,
        job_id: str,
        text: str,
        segments: list[dict[str, float | str]],
        language: str,
        processing_time_sec: float,
    ) -> Transcript | None:
        job = await self.get_job(job_id)
        if job is None:
            return None

        transcript = Transcript(
            job_id=job_id,
            text=text,
            segments_json=json.dumps(segments, ensure_ascii=False),
            language=language,
            processing_time_sec=processing_time_sec,
        )
        self.session.add(transcript)
        await self.session.commit()
        await self.session.refresh(transcript)
        return transcript

    async def get_or_create_telegram_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
    ) -> TelegramUser:
        user = await self.get_telegram_user(user_id)
        if user is not None:
            user.username = username
            user.first_name = first_name
            await self.session.commit()
            await self.session.refresh(user)
            return user

        user = TelegramUser(
            user_id=user_id,
            username=username,
            first_name=first_name,
            is_trusted=False,
            awaiting_auth_answer=False,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_telegram_user(self, user_id: int) -> TelegramUser | None:
        stmt = select(TelegramUser).where(TelegramUser.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_telegram_user_awaiting_auth(self, user_id: int, awaiting: bool) -> TelegramUser | None:
        user = await self.get_telegram_user(user_id)
        if user is None:
            return None
        user.awaiting_auth_answer = awaiting
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_telegram_user_trusted(self, user_id: int, trusted: bool) -> TelegramUser | None:
        user = await self.get_telegram_user(user_id)
        if user is None:
            return None
        user.is_trusted = trusted
        if trusted:
            user.awaiting_auth_answer = False
            user.auth_granted_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_telegram_user_last_job(self, user_id: int, job_id: str) -> TelegramUser | None:
        user = await self.get_telegram_user(user_id)
        if user is None:
            return None
        user.last_job_id = job_id
        await self.session.commit()
        await self.session.refresh(user)
        return user
