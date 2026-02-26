import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

try:
    from aiogram.exceptions import TelegramBadRequest
except ModuleNotFoundError:  # pragma: no cover - allows tests without optional bot deps
    class TelegramBadRequest(Exception):
        pass

from app.core.config import Settings
from app.db.models import JobStatus
from app.db.repository import JobRepository
from app.media.processing import (
    MediaProcessingError,
    audio_duration_seconds,
    cleanup_file,
    normalize_audio,
)
from app.tasks.manager import JobManager, QueueFullError

logger = logging.getLogger(__name__)


@dataclass
class TelegramMedia:
    file_id: str
    original_filename: str
    file_size_bytes: int | None = None


@dataclass
class JobStatusSnapshot:
    exists: bool
    status: str | None
    progress: int | None
    error_message: str | None
    text: str | None
    original_filename: str | None


class TelegramTranscriptionService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker,
        job_manager: JobManager,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.job_manager = job_manager
        self._watch_tasks: set[asyncio.Task] = set()

    def can_download_large_files(self) -> bool:
        return (
            self.settings.telegram_pyrogram_enabled
            and self.settings.telegram_api_id is not None
            and bool(self.settings.telegram_api_hash)
            and bool(self.settings.telegram_bot_token)
        )

    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            await repo.get_or_create_telegram_user(user_id, username, first_name)

    async def begin_auth(self, user_id: int) -> None:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            await repo.set_telegram_user_awaiting_auth(user_id, awaiting=True)

    async def is_trusted(self, user_id: int) -> bool:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            user = await repo.get_telegram_user(user_id)
            return bool(user and user.is_trusted)

    async def try_authorize(self, user_id: int, answer: str) -> bool:
        expected = self.settings.telegram_auth_answer.strip().casefold()
        provided = answer.strip().casefold()
        if not expected or provided != expected:
            return False
        async with self.session_factory() as session:
            repo = JobRepository(session)
            await repo.set_telegram_user_trusted(user_id, trusted=True)
        return True

    async def is_awaiting_auth(self, user_id: int) -> bool:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            user = await repo.get_telegram_user(user_id)
            return bool(user and user.awaiting_auth_answer)

    async def enqueue_from_telegram(self, bot, user_id: int, media: TelegramMedia) -> str:
        source_path: Path | None = None
        normalized_path: Path | None = None
        try:
            source_path = await self._download_file(bot, media)
            normalized_path = normalize_audio(source_path, self.settings)
            duration = audio_duration_seconds(normalized_path)
            if duration > self.settings.max_duration_sec:
                raise MediaProcessingError(
                    f"Audio too long. Max duration is {self.settings.max_duration_sec} seconds"
                )
            job = await self.job_manager.enqueue(
                source_file_path=source_path,
                normalized_path=normalized_path,
                original_filename=media.original_filename,
                duration_sec=duration,
                language=self.settings.language_default,
            )
            self.job_manager.schedule_detached(job.id)
            async with self.session_factory() as session:
                repo = JobRepository(session)
                await repo.set_telegram_user_last_job(user_id, job.id)
            return job.id
        except QueueFullError:
            if normalized_path is not None:
                cleanup_file(normalized_path)
            if source_path is not None and source_path != normalized_path:
                cleanup_file(source_path)
            logger.warning("Telegram queue is full for user_id=%s", user_id)
            raise
        except TelegramBadRequest as exc:
            if normalized_path is not None:
                cleanup_file(normalized_path)
            if source_path is not None and source_path != normalized_path:
                cleanup_file(source_path)
            message = str(exc)
            if "file is too big" in message.lower():
                raise MediaProcessingError(
                    "Файл слишком большой для загрузки через Telegram Bot API. "
                    "Отправьте файл меньшего размера."
                ) from exc
            raise MediaProcessingError(f"Ошибка Telegram API: {message}") from exc
        except Exception:
            if normalized_path is not None:
                cleanup_file(normalized_path)
            if source_path is not None and source_path != normalized_path:
                cleanup_file(source_path)
            logger.exception("Telegram enqueue failed for user_id=%s", user_id)
            raise

    async def get_last_job_snapshot(self, user_id: int) -> JobStatusSnapshot:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            user = await repo.get_telegram_user(user_id)
            if user is None or not user.last_job_id:
                return JobStatusSnapshot(False, None, None, None, None, None)
            return await self._build_job_snapshot(repo, user.last_job_id)

    async def get_job_snapshot(self, job_id: str) -> JobStatusSnapshot:
        async with self.session_factory() as session:
            repo = JobRepository(session)
            return await self._build_job_snapshot(repo, job_id)

    async def _build_job_snapshot(self, repo: JobRepository, job_id: str) -> JobStatusSnapshot:
        job = await repo.get_job(job_id)
        if job is None:
            return JobStatusSnapshot(False, None, None, None, None, None)
        transcript_text = job.transcript.text if job.transcript is not None else None
        return JobStatusSnapshot(
            exists=True,
            status=job.status,
            progress=job.progress,
            error_message=job.error_message,
            text=transcript_text,
            original_filename=job.original_filename,
        )

    def schedule_result_delivery(self, bot, chat_id: int, job_id: str) -> None:
        task = asyncio.create_task(self._watch_and_send(bot, chat_id, job_id))
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)

    async def _watch_and_send(self, bot, chat_id: int, job_id: str) -> None:
        started = time.perf_counter()
        timeout = self.settings.telegram_result_wait_timeout_sec
        interval = max(0.5, self.settings.telegram_status_poll_interval_sec)
        while True:
            status_snapshot = await self.get_job_snapshot(job_id)
            if not status_snapshot.exists:
                await bot.send_message(chat_id, "Не удалось найти задачу для отправки результата.")
                return

            if status_snapshot.status == JobStatus.DONE:
                text = status_snapshot.text or ""
                filename = _txt_filename_from_original(status_snapshot.original_filename)
                self.settings.temp_path.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".txt",
                    delete=False,
                    encoding="utf-8",
                    dir=self.settings.temp_path,
                ) as tmp:
                    tmp.write(text)
                    tmp_path = Path(tmp.name)
                try:
                    from aiogram.types import FSInputFile

                    await bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(tmp_path, filename=filename),
                        caption="Расшифровка готова.",
                    )
                finally:
                    cleanup_file(tmp_path)
                return

            if status_snapshot.status == JobStatus.FAILED:
                reason = status_snapshot.error_message or "Ошибка распознавания"
                await bot.send_message(chat_id, f"Задача завершилась с ошибкой: {reason}")
                return

            if (time.perf_counter() - started) >= timeout:
                await bot.send_message(chat_id, "Превышено время ожидания результата. Проверьте /status позже.")
                return

            await asyncio.sleep(interval)

    async def _download_file(self, bot, media: TelegramMedia) -> Path:
        return await self._download_file_with_fallback(
            bot=bot,
            file_id=media.file_id,
            original_filename=media.original_filename,
            file_size_bytes=media.file_size_bytes,
        )

    async def _download_file_with_fallback(
        self, bot, file_id: str, original_filename: str, file_size_bytes: int | None = None
    ) -> Path:
        _bot_api_limit = 20 * 1024 * 1024
        suffix = Path(original_filename).suffix or ".bin"
        too_large_for_bot_api = file_size_bytes is not None and file_size_bytes > _bot_api_limit
        if self.can_download_large_files():
            try:
                return await self._download_file_via_pyrogram(file_id=file_id, suffix=suffix)
            except Exception as pyrogram_exc:
                if too_large_for_bot_api:
                    raise MediaProcessingError(
                        f"Не удалось скачать файл через Pyrogram (MTProto): {pyrogram_exc}. "
                        "Проверьте настройки TELEGRAM_API_ID / TELEGRAM_API_HASH и логи сервера."
                    ) from pyrogram_exc
                logger.exception("Pyrogram download failed, falling back to Bot API")

        file_meta = await bot.get_file(file_id)
        self.settings.temp_path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=self.settings.temp_path) as tmp_file:
            tmp_path = Path(tmp_file.name)
            await bot.download_file(file_meta.file_path, destination=tmp_file, timeout=300)
        return tmp_path

    async def _download_file_via_pyrogram(self, file_id: str, suffix: str) -> Path:
        if not self.can_download_large_files():
            raise MediaProcessingError("Pyrogram download is not configured")
        self.settings.temp_path.mkdir(parents=True, exist_ok=True)
        pyrogram_workdir = self.settings.temp_path / "pyrogram"
        pyrogram_workdir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=self.settings.temp_path) as tmp_file:
            tmp_path = Path(tmp_file.name)

        try:
            from pyrogram import Client

            async with Client(
                name=self.settings.telegram_pyrogram_session_name,
                api_id=self.settings.telegram_api_id,
                api_hash=self.settings.telegram_api_hash,
                bot_token=self.settings.telegram_bot_token,
                no_updates=True,
                workdir=str(pyrogram_workdir),
            ) as client:
                downloaded_path = await client.download_media(
                    message=file_id,
                    file_name=str(tmp_path),
                )
            if not downloaded_path:
                raise MediaProcessingError("Pyrogram did not return downloaded file path")
            return Path(downloaded_path)
        except Exception:
            cleanup_file(tmp_path)
            raise


def _txt_filename_from_original(original_filename: str | None) -> str:
    if not original_filename:
        return "transcript.txt"
    stem = Path(original_filename).stem or "transcript"
    return f"{stem}.txt"
