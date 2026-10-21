"""Redis streams between the backend and the ai worker.

backend -> ai: the backend adds jobs to AI_REQUEST_STREAM; the ai worker consumes them.
ai -> backend: the ai worker adds results to AI_RESULT_STREAM; one consumer loop in the api
process reads them through a consumer group, so every result is acked after handling and a
result that was not acked (crash, failed handler) is delivered again.

Every entry carries the same fields: event (the spec's name, e.g. ai:dispute:classify or
ai:result:classified), job_id, version, payload (json) and created_at.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from app.api.repo.streams import StreamRepository, SyncStreamRepository
from app.core.config import get_settings

SETTINGS = get_settings()

ENVELOPE_VERSION: str = "1"
MAX_BACKOFF_SECONDS: float = 30.0


@dataclass(frozen=True)
class StreamMessage:
    id: str  # redis entry id
    event: str
    job_id: str
    version: str
    payload: dict
    created_at: str
    deliveries: int  # 1 on first delivery


Handler = Callable[[StreamMessage], Awaitable[None]]


def _envelope(event: str, job_id: str, payload: dict) -> dict:
    return {
        "event": event,
        "job_id": job_id,
        "version": ENVELOPE_VERSION,
        "payload": json.dumps(payload),
        "created_at": datetime.now(UTC).isoformat(),
    }


def publish_ai_job_sync(redis: SyncRedis, event: str, payload: dict, job_id: str) -> str:
    """AiStreamPublisher.publish for celery tasks, which run without an event loop"""
    SyncStreamRepository(redis).add(
        SETTINGS.AI_REQUEST_STREAM, _envelope(event, job_id, payload), SETTINGS.AI_STREAM_MAXLEN
    )
    sentry_logger.info(
        "Published {event} job {job_id} to the ai worker", event=event, job_id=job_id
    )
    return job_id


class AiStreamPublisher:
    """backend -> ai"""

    def __init__(self, async_redis: Redis):
        self._streams = StreamRepository(async_redis)

    async def publish(self, event: str, payload: dict, job_id: str | None = None) -> str:
        """Adds a job for the ai worker and returns its job id (for correlating the result)"""
        job_id = job_id or str(uuid.uuid4())
        await self._streams.add(
            SETTINGS.AI_REQUEST_STREAM,
            _envelope(event, job_id, payload),
            SETTINGS.AI_STREAM_MAXLEN,
        )
        sentry_logger.info(
            "Published {event} job {job_id} to the ai worker", event=event, job_id=job_id
        )
        return job_id


class AiResultConsumer:
    """ai -> backend: one loop, run as an asyncio task from the lifespan"""

    def __init__(
        self,
        async_redis: Redis,
        handlers: dict[str, Handler],
        stream: str = SETTINGS.AI_RESULT_STREAM,
        group: str = SETTINGS.AI_RESULT_GROUP,
        consumer: str = SETTINGS.AI_RESULT_CONSUMER,
        max_deliveries: int = SETTINGS.AI_RESULT_MAX_DELIVERIES,
        block_ms: int = SETTINGS.AI_RESULT_BLOCK_MS,
        retry_pending_seconds: int = SETTINGS.AI_RESULT_RETRY_PENDING_SECONDS,
    ):
        self._streams = StreamRepository(async_redis)
        self._handlers = handlers
        self.stream = stream
        self.dead_letter_stream = f"{stream}:dead"
        self.group = group
        self.consumer = consumer
        self._max_deliveries = max_deliveries
        self._block_ms = block_ms
        self._retry_pending_seconds = retry_pending_seconds

    async def ensure_group(self):
        """Creates the stream and group when missing. Starting from 0 means results added
        before the group existed are still read"""
        await self._streams.ensure_group(self.stream, self.group)

    async def run(self):
        """Reads until cancelled. Redis errors restart the loop with backoff instead of
        ending the task"""
        backoff: float = 1.0
        task: asyncio.Task | None = asyncio.current_task()

        while True:
            try:
                await self.ensure_group()
                # this consumer's unacked results from before a restart come first
                await self.process_pending()
                last_pending_pass: float = monotonic()
                backoff = 1.0

                while True:
                    await self.process_new()

                    # a cancel that lands inside a redis call can be absorbed by the client
                    # (seen on python 3.11), which would leave this loop running forever
                    if task is not None and task.cancelling():
                        raise asyncio.CancelledError

                    # results whose handler failed stay pending; retry them periodically
                    if monotonic() - last_pending_pass >= self._retry_pending_seconds:
                        await self.process_pending()
                        last_pending_pass = monotonic()
            except asyncio.CancelledError:
                sentry_logger.info("Ai result consumer stopped")
                raise
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                sentry_logger.error(
                    "Ai result consumer failed, restarting in {seconds}s", seconds=str(backoff)
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def process_new(self) -> int:
        """Blocks up to block_ms for results never delivered before; returns how many"""
        entries = await self._streams.read_group(
            self.stream, self.group, self.consumer, ">", count=10, block_ms=self._block_ms
        )

        for entry_id, fields in entries:
            await self._process(entry_id, fields, deliveries=1)
        return len(entries)

    async def process_pending(self) -> int:
        """Re-reads this consumer's delivered but unacked results; returns how many"""
        processed: int = 0
        start_id: str = "0"

        while True:
            entries = await self._streams.read_group(
                self.stream, self.group, self.consumer, start_id, count=10
            )
            if not entries:
                return processed

            for entry_id, fields in entries:
                # entries trimmed from the stream come back without fields
                if not fields:
                    await self._streams.ack(self.stream, self.group, entry_id)
                    continue
                await self._process(entry_id, fields, await self._deliveries(entry_id))
                processed += 1

            start_id = entries[-1][0]

    async def _deliveries(self, entry_id: str) -> int:
        return await self._streams.deliveries(self.stream, self.group, entry_id)

    async def _process(self, entry_id: str, fields: dict, deliveries: int):
        if deliveries > self._max_deliveries:
            await self._dead_letter(entry_id, fields, "max_deliveries_exceeded", deliveries)
            return

        try:
            message = StreamMessage(
                id=entry_id,
                event=fields["event"],
                job_id=fields["job_id"],
                version=fields.get("version", ENVELOPE_VERSION),
                payload=json.loads(fields["payload"]),
                created_at=fields.get("created_at", ""),
                deliveries=deliveries,
            )
        except (KeyError, json.JSONDecodeError, TypeError):
            await self._dead_letter(entry_id, fields, "malformed", deliveries)
            return

        handler: Handler | None = self._handlers.get(message.event)
        if handler is None:
            # kept in the dead-letter stream rather than retried forever
            await self._dead_letter(entry_id, fields, "unhandled_event", deliveries)
            return

        try:
            await handler(message)
        except Exception as exc:
            # not acked: it stays pending and is retried on the next pending pass
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Handling {event} job {job_id} failed (delivery {deliveries})",
                event=message.event,
                job_id=message.job_id,
                deliveries=str(deliveries),
            )
            return

        await self._streams.ack(self.stream, self.group, entry_id)

    async def _dead_letter(self, entry_id: str, fields: dict, reason: str, deliveries: int):
        """Copies the result to the dead-letter stream and acks it, in one transaction"""
        await self._streams.move_and_ack(
            self.stream,
            self.group,
            entry_id,
            self.dead_letter_stream,
            {
                **fields,
                "original_id": entry_id,
                "reason": reason,
                "deliveries": str(deliveries),
                "dead_at": datetime.now(UTC).isoformat(),
            },
            SETTINGS.AI_STREAM_MAXLEN,
        )

        sentry_logger.error(
            "Ai result {entry_id} moved to {stream}: {reason}",
            entry_id=entry_id,
            stream=self.dead_letter_stream,
            reason=reason,
        )


# event -> handler for ai results; the processing functions are added with the dispute
# and trust modules (ai:result:classified, ai:result:evidence-generated,
# ai:result:quality-scored, ai:result:trust-explained, ai:result:state-change-summarized,
# ai:error)
AI_RESULT_HANDLERS: dict[str, Handler] = {}


async def stop_task(task: asyncio.Task | None):
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
