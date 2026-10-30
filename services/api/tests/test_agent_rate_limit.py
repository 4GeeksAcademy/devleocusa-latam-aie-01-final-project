from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from src.agent.rate_limit import RedisFixedWindowRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.count = 0
        self.ttl = 60

    async def eval(self, script, key_count, key, window):
        assert key_count == 1
        assert key.startswith("trackflow:agent-rate:")
        assert window == 60
        self.count += 1
        return self.count, self.ttl


def test_redis_rate_limiter_allows_only_configured_number_of_requests() -> None:
    limiter = RedisFixedWindowRateLimiter(FakeRedis(), limit=2, window_seconds=60)  # type: ignore[arg-type]

    async def exercise_limiter() -> None:
        assert await limiter.allow("user-1") == (True, 60)
        assert await limiter.allow("user-1") == (True, 60)
        assert await limiter.allow("user-1") == (False, 60)

    asyncio.run(exercise_limiter())


def test_rate_limiter_rejects_nonpositive_configuration() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        RedisFixedWindowRateLimiter(object(), limit=0, window_seconds=60)  # type: ignore[arg-type]


def test_rate_limiter_works_with_real_redis() -> None:
    """Run with REDIS_INTEGRATION_URL=redis://... to prove real Redis/Lua behavior."""
    redis_url = os.getenv("REDIS_INTEGRATION_URL", "").strip()
    if not redis_url:
        pytest.skip("Set REDIS_INTEGRATION_URL to run the real Redis integration test.")

    from redis.asyncio import Redis

    async def exercise_real_redis() -> None:
        client = Redis.from_url(redis_url, decode_responses=True)
        key = f"integration-{uuid.uuid4()}"
        limiter = RedisFixedWindowRateLimiter(client, limit=2, window_seconds=30)
        try:
            await limiter.verify_backend()
            assert await limiter.allow(key) == (True, 30)
            assert await limiter.allow(key) == (True, 30)
            allowed, retry_after = await limiter.allow(key)
            assert allowed is False
            assert 1 <= retry_after <= 30
        finally:
            await client.delete(f"trackflow:agent-rate:{key}")
            await client.aclose()

    asyncio.run(exercise_real_redis())
