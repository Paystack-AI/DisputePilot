"""Redis stream and counter commands behind the live events and the ai streams.
StreamRepository is async (the api); SyncStreamRepository covers what celery tasks need.
"""

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import ResponseError

# [(entry id, fields), ...]
Entries = list[tuple[str, dict]]


def _entries(response) -> Entries:
    # [[stream, [(id, fields), ...]]] or [] when nothing arrived
    return response[0][1] if response else []


class StreamRepository:
    def __init__(self, async_redis: Redis):
        self._async_redis = async_redis

    # ------------------------------ entries ------------------------------ #

    async def add(self, key: str, fields: dict, maxlen: int) -> str:
        """Appends an entry, trimming the stream to about maxlen; returns its id"""
        return await self._async_redis.xadd(key, fields, maxlen=maxlen, approximate=True)

    async def add_expiring(self, key: str, fields: dict, maxlen: int, ttl: int) -> str:
        """add, and the stream expires ttl seconds after its last entry"""
        async with self._async_redis.pipeline(transaction=True) as pipe:
            pipe.xadd(key, fields, maxlen=maxlen, approximate=True)
            pipe.expire(key, ttl)
            entry_id, _ = await pipe.execute()
        return entry_id

    async def newest_id(self, key: str) -> str | None:
        newest = await self._async_redis.xrevrange(key, count=1)
        return newest[0][0] if newest else None

    async def oldest_id(self, key: str) -> str | None:
        oldest = await self._async_redis.xrange(key, count=1)
        return oldest[0][0] if oldest else None

    async def range_after(self, key: str, after_id: str, count: int) -> Entries:
        """Entries after after_id (exclusive), oldest first"""
        return await self._async_redis.xrange(key, min=f"({after_id}", count=count)

    async def read_after(self, key: str, after_id: str, count: int, block_ms: int) -> Entries:
        """Entries after after_id, waiting up to block_ms for one to arrive"""
        return _entries(await self._async_redis.xread({key: after_id}, count=count, block=block_ms))

    # ------------------------------ consumer groups ------------------------------ #

    async def ensure_group(self, key: str, group: str):
        """Creates the stream and group when missing, reading from the start"""
        try:
            await self._async_redis.xgroup_create(key, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):  # already exists
                raise

    async def read_group(
        self,
        key: str,
        group: str,
        consumer: str,
        start_id: str,
        count: int,
        block_ms: int | None = None,
    ) -> Entries:
        """'>' reads entries never delivered; an id re-reads this consumer's pending ones"""
        return _entries(
            await self._async_redis.xreadgroup(
                group, consumer, {key: start_id}, count=count, block=block_ms
            )
        )

    async def ack(self, key: str, group: str, entry_id: str):
        await self._async_redis.xack(key, group, entry_id)

    async def deliveries(self, key: str, group: str, entry_id: str) -> int:
        """How many times the pending entry was delivered (1 when not pending)"""
        pending = await self._async_redis.xpending_range(
            key, group, min=entry_id, max=entry_id, count=1
        )
        return pending[0]["times_delivered"] if pending else 1

    async def move_and_ack(
        self, key: str, group: str, entry_id: str, to_key: str, fields: dict, maxlen: int
    ):
        """Copies the entry to another stream and acks it, in one transaction"""
        async with self._async_redis.pipeline(transaction=True) as pipe:
            pipe.xadd(to_key, fields, maxlen=maxlen, approximate=True)
            pipe.xack(key, group, entry_id)
            await pipe.execute()

    # ------------------------------ counters ------------------------------ #

    async def increment(self, key: str, ttl: int) -> int:
        """Adds one and (re)sets the expiry; returns the new count"""
        async with self._async_redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl)
            count, _ = await pipe.execute()
        return count

    async def decrement(self, key: str) -> int:
        return await self._async_redis.decr(key)

    async def touch(self, key: str, ttl: int):
        await self._async_redis.expire(key, ttl)


class SyncStreamRepository:
    def __init__(self, redis: SyncRedis):
        self._redis = redis

    def add_expiring(self, key: str, fields: dict, maxlen: int, ttl: int) -> str:
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(key, fields, maxlen=maxlen, approximate=True)
            pipe.expire(key, ttl)
            entry_id, _ = pipe.execute()
        return entry_id
