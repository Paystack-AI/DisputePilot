import time

from fastapi.requests import Request
from fastapi.responses import Response
from fastapi_limiter.callback import default_callback
from fastapi_limiter.depends import RateLimiter
from pyrate_limiter.abstracts.bucket import BucketFactory
from pyrate_limiter.abstracts.rate import Duration, Rate, RateItem
from pyrate_limiter.buckets.redis_bucket import RedisBucket
from pyrate_limiter.limiter import Limiter
from redis.asyncio import Redis

DURATION_MAPPING = {
    "hours": Duration.HOUR,
    "seconds": Duration.SECOND,
    "minutes": Duration.MINUTE,
}


async def client_identifier(request: Request):
    ip = request.client.host if request.client else "127.0.0.1"
    return f"{ip}:{request.scope['path']}"


class SafeRateLimiter(RateLimiter):
    """FastAPI includes internal _IncludedRouter entries in app.routes.

    Those objects do not expose .path/.methods, but the upstream library assumes
    every route does. Skip them so auth endpoints can still be rate-limited
    without crashing during route matching.
    """

    async def __call__(self, request: Request, response: Response):
        route_index = 0
        dep_index = 0
        for i, route in enumerate(request.app.routes):
            if not hasattr(route, "path"):
                continue
            if (
                route.path == request.scope["path"]
                and hasattr(route, "methods")
                and request.method in route.methods
            ):
                route_index = i
                if hasattr(route, "endpoint") and getattr(route.endpoint, "_skip_limiter", False):
                    return
                if hasattr(route, "dependencies"):
                    for j, dependency in enumerate(route.dependencies):
                        if self is dependency.dependency:
                            dep_index = j
                            break

        rate_key = await self.identifier(request)
        key = f"{rate_key}:{route_index}:{dep_index}"
        success = await self.limiter.try_acquire_async(key, blocking=self.blocking)
        if not success:
            return await self.callback(request, response)


class _PerIdentityRedisBucketFactory(BucketFactory):
    """Passing a bare RedisBucket straight to pyrate_limiter's Limiter() wraps
    it in SingleBucketFactory, which always routes every request to the
    SAME bucket regardless of the item's identity — RedisBucket's Lua
    script counts everything in that one Redis key with no per-item
    filtering. That makes a naive Limiter(bucket) setup a limit shared
    globally by every caller, not a per-client one, no matter what
    identifier is passed to RateLimiter.

    This instead builds a per-identity redis sorted set keyed off the item's
    fullname and Redis Lua Script counts separate bucket for each client
    """

    def __init__(self, rates: list[Rate], redis: Redis, key_prefix: str, script_hash: str):
        self._rates = rates
        self._redis = redis
        self._key_prefix = key_prefix
        self._script_hash = script_hash

    def wrap_item(self, name, weight: int = 1) -> RateItem:
        now_ms = time.time_ns() // 1_000_000
        return RateItem(name=name, timestamp=now_ms, weight=weight)

    def get(self, item):
        bucket_key = f"{self._key_prefix}:{item.name}"
        return RedisBucket(
            rates=self._rates,
            redis=self._redis,
            bucket_key=bucket_key,
            script_hash=self._script_hash,
        )


async def get_limiter(request: Request, config: tuple) -> RateLimiter:
    """Retrieve the RateLimiter for a given (key, limit, unit, multiplier)
    config, building it once per config and caching it on app.state.
    Each one owns a _PerIdentityRedisBucketFactory, so callers are scoped
    correctly by identity instead of sharing one global bucket.
    """

    redis: Redis = request.app.state.redis
    limiters: dict[tuple, RateLimiter] = request.app.state.limiters

    if config not in limiters:
        key, limit, unit, multiplier = config
        interval = DURATION_MAPPING.get(unit, Duration.MINUTE) * multiplier
        rates = [Rate(limit=limit, interval=interval)]

        # Throwaway bucket, used only to resolve the Lua script hash once.
        redis_bucket = await RedisBucket.init(rates=rates, redis=redis, bucket_key=key)

        factory = _PerIdentityRedisBucketFactory(
            rates=rates,
            redis=redis,
            key_prefix=key,
            script_hash=redis_bucket.script_hash,
        )
        limiter = Limiter(factory)

        rate_limiter = SafeRateLimiter(
            limiter=limiter,
            identifier=client_identifier,
            callback=default_callback,
        )

        limiters[config] = rate_limiter

    return limiters[config]


def _limiter_handler(key: str, limit: int, unit: str, multiplier: int = 1):
    async def _limiter(request: Request, response: Response):
        config = (key, limit, unit, multiplier)
        limiter: RateLimiter = await get_limiter(request, config)

        return await limiter(request, response)

    return _limiter
