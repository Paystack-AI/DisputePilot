from redis.asyncio import Redis

# Swap a hash field from an expected value to a new one in a single step, so two
# concurrent callers can never both succeed with the same expected value.
#   1  -> swapped
#   0  -> field missing
#  -1  -> field holds another value; the field is deleted, other fields are kept
ROTATE_HASH_FIELD_SCRIPT = """
local current = redis.call('HGET', KEYS[1], ARGV[1])
if not current then
    return 0
end
if current ~= ARGV[2] then
    redis.call('HDEL', KEYS[1], ARGV[1])
    return -1
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""

# Check a one-time code stored as {code, attempts} in a single step, so it can be
# used once and guessed at most max_attempts times. The key keeps its ttl.
#   1  -> matched; the key is deleted
#   0  -> no code (expired or never issued)
#  -1  -> wrong code and attempts exhausted; the key is deleted
#  -2  -> wrong code, attempts remaining
CONSUME_CODE_SCRIPT = """
local stored = redis.call('HGET', KEYS[1], 'code')
if not stored then
    return 0
end
if stored == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
    redis.call('DEL', KEYS[1])
    return -1
end
return -2
"""


class RedisRepository:
    def __init__(self, async_redis: Redis = None):
        self._async_redis = async_redis

    async def create_hset(self, key: str, value: dict, ttl: int | None = None):
        async with self._async_redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=value)
            if ttl:
                pipe.expire(key, ttl)
            await pipe.execute()

    async def get_hset(self, key: str) -> dict:
        return await self._async_redis.hgetall(key)

    async def hash_field_exists(self, key: str, field: str) -> bool:
        return bool(await self._async_redis.hexists(key, field))

    async def delete_hash_field(self, key: str, field: str) -> int:
        """Returns the number of fields deleted"""
        return await self._async_redis.hdel(key, field)

    async def rotate_hash_field(
        self, key: str, field: str, expected: str, value: str, ttl: int
    ) -> int:
        script = self._async_redis.register_script(ROTATE_HASH_FIELD_SCRIPT)
        return await script(keys=[key], args=[field, expected, value, ttl])

    async def consume_code(self, key: str, code: str, max_attempts: int) -> int:
        script = self._async_redis.register_script(CONSUME_CODE_SCRIPT)
        return await script(keys=[key], args=[code, max_attempts])

    async def set_key(self, key: str, value: str, ttl: int):
        await self._async_redis.set(key, value, ex=ttl)

    async def get_key(self, key: str) -> str | None:
        return await self._async_redis.get(key)

    async def delete_key(self, *keys: str) -> int:
        """Returns the number of keys deleted"""
        return await self._async_redis.delete(*keys)
