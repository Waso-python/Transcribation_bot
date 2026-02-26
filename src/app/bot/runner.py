import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers import create_router
from app.bot.service import TelegramTranscriptionService
from app.core.config import Settings
from app.tasks.manager import JobManager

logger = logging.getLogger(__name__)


class TelegramBotRunner:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker,
        job_manager: JobManager,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.job_manager = job_manager
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self.service: TelegramTranscriptionService | None = None
        self._polling_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.settings.telegram_enabled:
            logger.info("Telegram bot disabled by config")
            return
        if not self.settings.telegram_bot_token:
            logger.warning("Telegram bot is enabled, but TELEGRAM_BOT_TOKEN is empty")
            return

        self.bot = Bot(token=self.settings.telegram_bot_token)
        self.dispatcher = Dispatcher()
        self.service = TelegramTranscriptionService(
            settings=self.settings,
            session_factory=self.session_factory,
            job_manager=self.job_manager,
        )
        self.dispatcher.include_router(create_router(self.service))
        await self.bot.delete_webhook(drop_pending_updates=True)
        self._polling_task = asyncio.create_task(
            self.dispatcher.start_polling(self.bot, allowed_updates=self.dispatcher.resolve_used_update_types())
        )
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        if self.dispatcher is not None and self._polling_task is not None:
            await self.dispatcher.stop_polling()

        if self._polling_task is not None:
            self._polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._polling_task

        if self.bot is not None:
            await self.bot.session.close()
        logger.info("Telegram bot polling stopped")
