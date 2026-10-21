"""Provider health and cooldown state, shared by all worker instances through Redis."""

import time

from redis.asyncio import Redis


class ProviderHealthStore:
    """Tracks consecutive failures and cooldown deadlines per provider."""

    def __init__(
        self,
        redis: Redis,
        key_prefix: str,
        cooldown_seconds: int,
        failure_threshold: int,
    ) -> None:
        """Uses redis so every worker instance sees the same cooldown decisions."""
        self._redis = redis
        self._key_prefix = key_prefix.rstrip(":")
        self._cooldown_seconds = cooldown_seconds
        self._failure_threshold = max(failure_threshold, 1)

    def _failures_key(self, provider: str) -> str:
        return f"{self._key_prefix}:{provider}:failures"

    def _cooldown_key(self, provider: str) -> str:
        return f"{self._key_prefix}:{provider}:cooldown"

    async def is_available(self, provider: str) -> bool:
        """Returns False while the provider is cooling down."""
        return not bool(await self._redis.exists(self._cooldown_key(provider)))

    async def record_failure(self, provider: str) -> None:
        """Counts a failover-worthy failure and starts a cooldown at the threshold."""
        failures_key: str = self._failures_key(provider)
        cooldown_key: str = self._cooldown_key(provider)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(failures_key)
            pipe.expire(failures_key, max(self._cooldown_seconds * 2, 1))
            failures, _ = await pipe.execute()

        if int(failures) >= self._failure_threshold:
            await self._redis.set(
                cooldown_key,
                str(int(time.time()) + self._cooldown_seconds),
                ex=max(self._cooldown_seconds, 1),
            )
            # after the cooldown the provider starts with a clean failure count
            await self._redis.delete(failures_key)

    async def record_success(self, provider: str) -> None:
        """Clears the provider's failure count after a successful call."""
        await self._redis.delete(self._failures_key(provider), self._cooldown_key(provider))

    async def unavailable_until(self, provider: str) -> float | None:
        """Returns the cooldown deadline as a unix timestamp, or None when available."""
        value: str | None = await self._redis.get(self._cooldown_key(provider))
        return float(value) if value else None
