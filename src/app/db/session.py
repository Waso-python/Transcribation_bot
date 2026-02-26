from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base


settings = get_settings()
engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    if not settings.auto_create_tables:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ping_db() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
