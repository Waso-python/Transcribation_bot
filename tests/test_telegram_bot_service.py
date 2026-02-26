import asyncio
from types import SimpleNamespace

from app.bot.service import TelegramMedia, TelegramTranscriptionService
from app.core.config import get_settings
from app.db.repository import JobRepository
from conftest import build_wav_bytes


class _FakeBot:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def get_file(self, file_id: str):
        return SimpleNamespace(file_path=f"/tmp/{file_id}.wav")

    async def download_file(self, file_path: str, destination):
        destination.write(self.payload)
        destination.flush()


def test_telegram_user_authorization_repo_flow(client):
    session_factory = client.app.state.session_factory

    async def scenario() -> None:
        async with session_factory() as session:
            repo = JobRepository(session)
            user = await repo.get_or_create_telegram_user(1001, "tester", "Test")
            assert user.user_id == 1001
            assert not user.is_trusted
            assert not user.awaiting_auth_answer

            user = await repo.set_telegram_user_awaiting_auth(1001, awaiting=True)
            assert user is not None and user.awaiting_auth_answer

            user = await repo.set_telegram_user_trusted(1001, trusted=True)
            assert user is not None and user.is_trusted
            assert not user.awaiting_auth_answer
            assert user.auth_granted_at is not None

    asyncio.run(scenario())


def test_telegram_enqueue_creates_job_and_status_available(client):
    service = TelegramTranscriptionService(
        settings=get_settings(),
        session_factory=client.app.state.session_factory,
        job_manager=client.app.state.job_manager,
    )
    bot = _FakeBot(build_wav_bytes(seconds=1))

    async def scenario() -> None:
        await service.ensure_user(1002, "audio_user", "Audio")
        job_id = await service.enqueue_from_telegram(
            bot=bot,
            user_id=1002,
            media=TelegramMedia(file_id="f-1", original_filename="sample.wav"),
        )
        assert job_id

        snapshot = await service.get_last_job_snapshot(1002)
        assert snapshot.exists
        assert snapshot.status in {"queued", "processing", "done"}

        for _ in range(50):
            job_snapshot = await service.get_job_snapshot(job_id)
            if job_snapshot.status == "done":
                assert job_snapshot.text
                return
            await asyncio.sleep(0.05)
        raise AssertionError("telegram enqueue job did not finish in time")

    asyncio.run(scenario())


def test_can_download_large_files_with_pyrogram_config(client):
    settings = get_settings().model_copy(
        update={
            "telegram_pyrogram_enabled": True,
            "telegram_api_id": 123456,
            "telegram_api_hash": "hash",
            "telegram_bot_token": "token",
        }
    )
    service = TelegramTranscriptionService(
        settings=settings,
        session_factory=client.app.state.session_factory,
        job_manager=client.app.state.job_manager,
    )

    assert service.can_download_large_files() is True
