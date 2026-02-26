import json
from typing import Any

from redis.asyncio import Redis


class RedisCache:
    def __init__(self, redis_url: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self._client: Redis | None = Redis.from_url(redis_url) if enabled else None

    async def ping(self) -> bool:
        if not self.enabled or self._client is None:
            return True
        try:
            pong = await self._client.ping()
            return bool(pong)
        except Exception:
            return False

    async def set_job_status(self, job_id: str, payload: dict[str, Any]) -> None:
        if not self.enabled or self._client is None:
            return
        await self._client.setex(f"job:{job_id}", 3600, json.dumps(payload))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
