import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.service import JobStatusSnapshot, TelegramMedia, TelegramTranscriptionService
from app.media.processing import MediaProcessingError
from app.tasks.manager import QueueFullError

logger = logging.getLogger(__name__)


def create_router(service: TelegramTranscriptionService) -> Router:
    router = Router(name="telegram_transcribe_bot")

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        if message.from_user is None:
            return
        await service.ensure_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if await service.is_trusted(message.from_user.id):
            await message.answer(
                "Вы авторизованы. Отправьте аудиофайл для распознавания или используйте /status."
            )
            return

        await service.begin_auth(message.from_user.id)
        await message.answer(service.settings.telegram_auth_question)

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        if message.from_user is None:
            return
        await service.ensure_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if not await service.is_trusted(message.from_user.id):
            await message.answer("Сначала пройдите авторизацию через /start.")
            return

        snapshot = await service.get_last_job_snapshot(message.from_user.id)
        await message.answer(_format_status(snapshot))

    @router.message(F.text)
    async def text_handler(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        await service.ensure_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if await service.is_trusted(message.from_user.id):
            return
        if not await service.is_awaiting_auth(message.from_user.id):
            await message.answer("Нажмите /start для авторизации.")
            return

        authorized = await service.try_authorize(message.from_user.id, message.text)
        if authorized:
            await message.answer("Доступ выдан. Теперь отправьте аудиофайл.")
            return
        await message.answer("Неверный ответ. Попробуйте снова или отправьте /start.")

    @router.message(F.audio | F.voice | F.document)
    async def media_handler(message: Message) -> None:
        if message.from_user is None:
            return
        await service.ensure_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if not await service.is_trusted(message.from_user.id):
            await message.answer("Сначала пройдите авторизацию через /start.")
            return

        media = _extract_media(message)
        if media is None:
            await message.answer("Поддерживаются только аудио/voice-файлы.")
            return
        if (
            media.file_size_bytes is not None
            and media.file_size_bytes > _telegram_download_limit_bytes()
            and not service.can_download_large_files()
        ):
            await message.answer(
                "Файл слишком большой для Telegram Bot API (лимит загрузки ботом около 20 MB). "
                "Включите загрузку через Pyrogram (MTProto) или отправьте меньший файл."
            )
            return

        await message.answer("Файл получен. Запускаю распознавание...")
        try:
            job_id = await service.enqueue_from_telegram(message.bot, message.from_user.id, media)
        except QueueFullError:
            await message.answer("Очередь перегружена. Повторите попытку позже.")
            return
        except MediaProcessingError as exc:
            await message.answer(f"Ошибка обработки аудио: {exc}")
            return
        except Exception as exc:
            logger.exception("Unexpected telegram media processing error")
            await message.answer(f"Не удалось обработать файл: {exc}")
            return

        await message.answer(f"Задача принята: `{job_id}`", parse_mode="Markdown")
        service.schedule_result_delivery(
            bot=message.bot,
            chat_id=message.chat.id,
            job_id=job_id,
        )

    return router


def _extract_media(message: Message) -> TelegramMedia | None:
    if message.audio is not None:
        return TelegramMedia(
            file_id=message.audio.file_id,
            original_filename=message.audio.file_name or f"audio-{message.audio.file_unique_id}.mp3",
            file_size_bytes=message.audio.file_size,
        )
    if message.voice is not None:
        return TelegramMedia(
            file_id=message.voice.file_id,
            original_filename=f"voice-{message.voice.file_unique_id}.ogg",
            file_size_bytes=message.voice.file_size,
        )
    if message.document is not None:
        mime_type = (message.document.mime_type or "").lower()
        filename = message.document.file_name or f"doc-{message.document.file_unique_id}.bin"
        if mime_type.startswith("audio/") or _has_audio_extension(filename):
            return TelegramMedia(
                file_id=message.document.file_id,
                original_filename=filename,
                file_size_bytes=message.document.file_size,
            )
    return None


def _has_audio_extension(filename: str) -> bool:
    ext = filename.rsplit(".", maxsplit=1)[-1].lower()
    return ext in {"wav", "mp3", "ogg", "m4a", "flac", "aac", "wma", "opus", "mp4"}


def _telegram_download_limit_bytes() -> int:
    # Telegram Bot API getFile hard limit for downloadable file size.
    return 20 * 1024 * 1024


def _format_status(snapshot: JobStatusSnapshot) -> str:
    if not snapshot.exists:
        return "У вас пока нет задач."
    status = snapshot.status or "unknown"
    progress = snapshot.progress if snapshot.progress is not None else 0
    if status == "failed" and snapshot.error_message:
        return f"Статус: {status} ({progress}%). Ошибка: {snapshot.error_message}"
    return f"Статус: {status} ({progress}%)."
