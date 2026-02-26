from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.manager import JobManager


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


def get_session_factory(request: Request):
    return request.app.state.session_factory


def get_asr_engine(request: Request):
    return request.app.state.asr_engine


async def get_db_session(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:  # type: AsyncSession
        yield session
