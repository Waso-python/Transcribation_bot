from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.api.routes import router
from app.asr.factory import build_asr_engine
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.request_id import RequestIDMiddleware
from app.db.session import SessionLocal, init_db
from app.storage.redis_cache import RedisCache
from app.tasks.manager import JobManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    settings.temp_path.mkdir(parents=True, exist_ok=True)
    await init_db()

    asr_engine = build_asr_engine(settings)
    await asr_engine.warmup()
    cache = RedisCache(redis_url=settings.redis_url, enabled=settings.redis_enabled)
    app.state.asr_engine = asr_engine
    app.state.cache = cache
    app.state.session_factory = SessionLocal
    app.state.job_manager = JobManager(
        settings=settings,
        session_factory=SessionLocal,
        asr_engine=asr_engine,
        cache=cache,
    )
    app.state.telegram_bot_runner = None
    if settings.telegram_enabled:
        try:
            from app.bot.runner import TelegramBotRunner
        except ImportError:
            logger.exception("Telegram bot dependencies are missing; bot will not start")
        else:
            bot_runner = TelegramBotRunner(
                settings=settings,
                session_factory=SessionLocal,
                job_manager=app.state.job_manager,
            )
            await bot_runner.start()
            app.state.telegram_bot_runner = bot_runner
    yield
    bot_runner = getattr(app.state, "telegram_bot_runner", None)
    if bot_runner is not None:
        await bot_runner.stop()
    await cache.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Transcribation Server", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router)
    return app


app = create_app()
