import asyncio
import hashlib
import json
import logging

import httpx
from aiolimiter import AsyncLimiter

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 5.0  # seconds


class OpenF1Client:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._limiter_per_second = AsyncLimiter(2, 1.0)
        self._limiter_per_minute = AsyncLimiter(25, 60.0)

    async def get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        for attempt in range(MAX_RETRIES):
            await self._limiter_per_second.acquire()
            await self._limiter_per_minute.acquire()
            logger.debug("GET %s params=%s", endpoint, params)
            resp = await self._client.get(endpoint, params=params)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (attempt + 1)
                logger.warning("Rate limited on %s, retrying in %.0fs", endpoint, wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return []

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def hash_event(data: dict) -> str:
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(canonical.encode()).hexdigest()
