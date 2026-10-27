from __future__ import annotations

import os
from typing import Protocol

from redis.asyncio import Redis


class RateLimiter(Protocol):
    async def allow(self, key: str) -> tuple[bool, int]: ...


class RedisFixedWindowRateLimiter:
    """Atomic per-user fixed-window limiter backed by shared Redis storage."""

    _SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

    def __init__(self, redis: Redis, *, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit values must be positive integers.")
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds

    async def allow(self, key: str) -> tuple[bool, int]:
        count, ttl = await self.redis.eval(
            self._SCRIPT,
            1,
            f"trackflow:agent-rate:{key}",
            self.window_seconds,
        )
        retry_after = max(int(ttl), 1)
        return int(count) <= self.limit, retry_after


def create_agent_rate_limiter() -> RedisFixedWindowRateLimiter:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL is required to protect model invocation endpoints.")
    limit = int(os.getenv("AGENT_RATE_LIMIT", "20"))
    window = int(os.getenv("AGENT_RATE_WINDOW_SECONDS", "60"))
    redis = Redis.from_url(redis_url, decode_responses=True)
    return RedisFixedWindowRateLimiter(redis, limit=limit, window_seconds=window)
