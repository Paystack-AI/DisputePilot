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

from app.api.repo.streams import StreamRepository, SyncStreamRepository
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
    return await StreamRepository(redis).add_expiring(
        stream_key(merchant_id),
        _fields(event_type, data),
        SETTINGS.EVENT_STREAM_MAXLEN,
        SETTINGS.EVENT_STREAM_TTL_SECONDS,
    )


def publish_event_sync(
    redis: SyncRedis, merchant_id: UUID | str, event_type: str, data: dict
) -> str:
    """publish_event for celery tasks, which run without an event loop"""
    return SyncStreamRepository(redis).add_expiring(
        stream_key(merchant_id),
        _fields(event_type, data),
        SETTINGS.EVENT_STREAM_MAXLEN,
        SETTINGS.EVENT_STREAM_TTL_SECONDS,
    )


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


async def _start(repo: StreamRepository, key: str, last_event_id: str | None) -> tuple[str, bool]:
    """Where the connection starts reading, and whether the client must resync (refetch
    everything) because events it missed are no longer kept"""
    newest_id: str | None = await repo.newest_id(key)

    # a fresh connection: only events from now on
    if not last_event_id or not STREAM_ID.match(last_event_id):
        return newest_id or "0-0", False

    oldest_id: str | None = await repo.oldest_id(key)

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

    repo = StreamRepository(redis)
    position, resync = await _start(repo, key, last_event_id)

    if resync:
        yield sse("resync", {})
    elif last_event_id and position == last_event_id:
        # replay everything after the client's last event, in batches
        while True:
            entries = await repo.range_after(key, position, REPLAY_BATCH)
            for entry_id, fields in entries:
                yield _from_entry(entry_id, fields)
                position = entry_id
            if len(entries) < REPLAY_BATCH:
                break

    last_check: float = monotonic()
    block_ms: int = max(int(heartbeat_seconds * 1000), 1)

    while True:
        entries = await repo.read_after(key, position, 100, block_ms)

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


# ------------------------------ open streams per merchant ------------------------------ #


def _connections_key(merchant_id: UUID | str) -> str:
    return f"events:connections:{merchant_id}"


def _connections_ttl() -> int:
    """A few heartbeats: refreshed on each, so it only lapses once no stream is alive"""
    return max(int(SETTINGS.EVENT_HEARTBEAT_SECONDS * 3), 1)


async def acquire_stream_slot(redis: Redis, merchant_id: UUID | str) -> bool:
    """Counts a new stream for the merchant; False (and not counted) over the cap. The
    count expires if a process dies without releasing it"""
    repo = StreamRepository(redis)
    key: str = _connections_key(merchant_id)
    if await repo.increment(key, _connections_ttl()) > SETTINGS.EVENT_MAX_STREAMS_PER_MERCHANT:
        await repo.decrement(key)
        return False
    return True


async def refresh_stream_slot(redis: Redis, merchant_id: UUID | str):
    """Keeps the count alive while the stream is open"""
    await StreamRepository(redis).touch(_connections_key(merchant_id), _connections_ttl())


async def release_stream_slot(redis: Redis, merchant_id: UUID | str):
    await StreamRepository(redis).decrement(_connections_key(merchant_id))
