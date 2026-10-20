"""Server-sent events for the dashboard: one redis stream per merchant.

publish_event adds to events:merchant:{merchant_id} (capped, expiring when idle); every open
GET /events connection of that merchant reads it from its own position, so each tab gets
every event. The stream entry id is the SSE id: EventSource sends it back as Last-Event-ID
when it reconnects, and the connection replays what it missed from there.
"""

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from redis import Redis as SyncRedis
from redis.asyncio import Redis

from app.core.config import get_settings

SETTINGS = get_settings()

# redis stream ids: <milliseconds>-<sequence>
STREAM_ID = re.compile(r"^\d+-\d+$")
REPLAY_BATCH: int = 200
# tells EventSource how long to wait before reconnecting, in ms
RECONNECT_MS: int = 3000


def stream_key(merchant_id: UUID | str) -> str:
    return f"events:merchant:{merchant_id}"


def _fields(event_type: str, data: dict) -> dict:
    return {"type": event_type, "data": json.dumps(data), "at": datetime.now(UTC).isoformat()}


async def publish_event(redis: Redis, merchant_id: UUID | str, event_type: str, data: dict) -> str:
    """Pushes an event to the merchant's open dashboards (and keeps it for replay); returns
    its id. Use from the api; celery tasks use publish_event_sync"""
    key: str = stream_key(merchant_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.xadd(
            key,
            _fields(event_type, data),
            maxlen=SETTINGS.EVENT_STREAM_MAXLEN,
            approximate=True,
        )
        pipe.expire(key, SETTINGS.EVENT_STREAM_TTL_SECONDS)
        entry_id, _ = await pipe.execute()
    return entry_id


def publish_event_sync(
    redis: SyncRedis, merchant_id: UUID | str, event_type: str, data: dict
) -> str:
    """publish_event for celery tasks, which run without an event loop"""
    key: str = stream_key(merchant_id)
    with redis.pipeline(transaction=True) as pipe:
        pipe.xadd(
            key,
            _fields(event_type, data),
            maxlen=SETTINGS.EVENT_STREAM_MAXLEN,
            approximate=True,
        )
        pipe.expire(key, SETTINGS.EVENT_STREAM_TTL_SECONDS)
        entry_id, _ = pipe.execute()
    return entry_id


def sse(event: str, data: dict, event_id: str | None = None) -> str:
    """One server-sent event"""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


def _from_entry(entry_id: str, fields: dict) -> str:
    try:
        data: dict = json.loads(fields.get("data") or "{}")
    except ValueError:
        data = {}
    return sse(fields.get("type", "message"), data, entry_id)


def _parse_id(entry_id: str) -> tuple[int, int]:
    milliseconds, sequence = entry_id.split("-")
    return int(milliseconds), int(sequence)


async def _start(redis: Redis, key: str, last_event_id: str | None) -> tuple[str, bool]:
    """Where the connection starts reading, and whether the client must resync (refetch
    everything) because events it missed are no longer kept"""
    newest = await redis.xrevrange(key, count=1)
    newest_id: str | None = newest[0][0] if newest else None

    # a fresh connection: only events from now on
    if not last_event_id or not STREAM_ID.match(last_event_id):
        return newest_id or "0-0", False

    oldest = await redis.xrange(key, count=1)
    oldest_id: str | None = oldest[0][0] if oldest else None

    if newest_id is None:
        # the stream expired while the client was away: anything it missed is gone
        return "0-0", True
    if _parse_id(last_event_id) > _parse_id(newest_id):
        # an id this stream never issued (another environment, a cleared redis)
        return newest_id, True
    if _parse_id(last_event_id) < _parse_id(oldest_id):
        # events after it may have been trimmed
        return newest_id, True
    return last_event_id, False


async def event_stream(
    redis: Redis,
    merchant_id: UUID | str,
    last_event_id: str | None,
    session_valid: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float = SETTINGS.EVENT_HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """The body of one GET /events connection. Replays what the client missed, then follows
    new events; while idle it sends a heartbeat comment. Every heartbeat interval it checks
    the session (token expiry, logout) and ends with session_expired when it is over"""
    key: str = stream_key(merchant_id)
    yield f"retry: {RECONNECT_MS}\n\n"

    position, resync = await _start(redis, key, last_event_id)

    if resync:
        yield sse("resync", {})
    elif last_event_id and position == last_event_id:
        # replay everything after the client's last event, in batches
        while True:
            entries = await redis.xrange(key, min=f"({position}", count=REPLAY_BATCH)
            for entry_id, fields in entries:
                yield _from_entry(entry_id, fields)
                position = entry_id
            if len(entries) < REPLAY_BATCH:
                break

    last_check: float = monotonic()
    block_ms: int = max(int(heartbeat_seconds * 1000), 1)

    while True:
        response = await redis.xread({key: position}, count=100, block=block_ms)
        entries = response[0][1] if response else []

        for entry_id, fields in entries:
            yield _from_entry(entry_id, fields)
            position = entry_id

        if monotonic() - last_check >= heartbeat_seconds or not entries:
            if not await session_valid():
                yield sse("session_expired", {})
                return
            last_check = monotonic()
            if not entries:
                # a comment line: keeps proxies from closing an idle connection
                yield ": ping\n\n"
