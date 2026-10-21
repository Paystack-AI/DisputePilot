"""Redis streams between the backend and the ai worker, the worker's side.

backend -> ai: the backend adds jobs to AI_REQUEST_STREAM. One consumer loop here reads them
through a consumer group, so every job is acked after handling and a job that was not acked
(crash, failed handler) is delivered again.
ai -> backend: the worker adds results to AI_RESULT_STREAM with the job's job_id, so the
backend can match the result to the job.

Every entry carries the same fields as on the backend: event (the spec's name, e.g.
ai:dispute:classify or ai:result:classified), job_id, version, payload (json) and created_at.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

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


class AiResultPublisher:
    """ai -> backend"""

    def __init__(self, async_redis: Redis, settings: Settings | None = None):
        self._redis = async_redis
        self._settings = settings or get_settings()

    async def publish(self, event: str, job_id: str, payload: dict) -> str:
        """Adds a result for the backend; job_id is the job's, so the backend can match them.
        Returns the redis entry id"""
        entry_id: str = await self._redis.xadd(
            self._settings.AI_RESULT_STREAM,
            {
                "event": event,
                "job_id": job_id,
                "version": ENVELOPE_VERSION,
                "payload": json.dumps(payload),
                "created_at": datetime.now(UTC).isoformat(),
            },
            maxlen=self._settings.AI_STREAM_MAXLEN,
            approximate=True,
        )
        logger.info("Published %s for job %s to the backend", event, job_id)
        return entry_id


class AiRequestConsumer:
    """backend -> ai: one loop, run by the worker (src.worker)"""

    def __init__(
        self,
        async_redis: Redis,
        handlers: dict[str, Handler],
        settings: Settings | None = None,
        stream: str | None = None,
        group: str | None = None,
        consumer: str | None = None,
        max_deliveries: int | None = None,
        block_ms: int | None = None,
        retry_pending_seconds: int | None = None,
    ):
        settings = settings or get_settings()
        self._redis = async_redis
        self._handlers = handlers
        self.stream = stream or settings.AI_REQUEST_STREAM
        self.dead_letter_stream = f"{self.stream}:dead"
        self.group = group or settings.AI_REQUEST_GROUP
        self.consumer = consumer or settings.AI_REQUEST_CONSUMER
        self._max_deliveries = max_deliveries or settings.AI_REQUEST_MAX_DELIVERIES
        self._block_ms = block_ms if block_ms is not None else settings.AI_REQUEST_BLOCK_MS
        self._retry_pending_seconds = (
            retry_pending_seconds
            if retry_pending_seconds is not None
            else settings.AI_REQUEST_RETRY_PENDING_SECONDS
        )
        self._maxlen = settings.AI_STREAM_MAXLEN

    async def ensure_group(self):
        """Creates the stream and group when missing. Starting from 0 means jobs added
        before the group existed are still read"""
        try:
            await self._redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):  # already exists
                raise

    async def run(self):
        """Reads until cancelled. Redis errors restart the loop with backoff instead of
        ending the task"""
        backoff: float = 1.0
        task: asyncio.Task | None = asyncio.current_task()

        while True:
            try:
                await self.ensure_group()
                # this consumer's unacked jobs from before a restart come first
                await self.process_pending()
                last_pending_pass: float = monotonic()
                backoff = 1.0

                while True:
                    await self.process_new()
                    # let other tasks run even when a read returns without waiting on io
                    # (an in-memory client, or a stream that always has entries)
                    await asyncio.sleep(0)

                    # a cancel that lands inside a redis call can be absorbed by the client
                    # (seen on python 3.11), which would leave this loop running forever
                    if task is not None and task.cancelling():
                        raise asyncio.CancelledError

                    # jobs whose handler failed stay pending; retry them periodically
                    if monotonic() - last_pending_pass >= self._retry_pending_seconds:
                        await self.process_pending()
                        last_pending_pass = monotonic()
            except asyncio.CancelledError:
                logger.info("Ai request consumer stopped")
                raise
            except Exception:
                logger.exception("Ai request consumer failed, restarting in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def process_new(self) -> int:
        """Blocks up to block_ms for jobs never delivered before; returns how many"""
        response = await self._redis.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=10,
            # 0 means don't block: redis's own BLOCK 0 would wait forever
            block=self._block_ms or None,
        )
        entries = self._entries(response)

        for entry_id, fields in entries:
            await self._process(entry_id, fields, deliveries=1)
        return len(entries)

    async def process_pending(self) -> int:
        """Re-reads this consumer's delivered but unacked jobs; returns how many"""
        processed: int = 0
        start_id: str = "0"

        while True:
            response = await self._redis.xreadgroup(
                self.group, self.consumer, {self.stream: start_id}, count=10
            )
            entries = self._entries(response)
            if not entries:
                return processed

            for entry_id, fields in entries:
                # entries trimmed from the stream come back without fields
                if not fields:
                    await self._redis.xack(self.stream, self.group, entry_id)
                    continue
                await self._process(entry_id, fields, await self._deliveries(entry_id))
                processed += 1

            start_id = entries[-1][0]

    async def _deliveries(self, entry_id: str) -> int:
        pending = await self._redis.xpending_range(
            self.stream, self.group, min=entry_id, max=entry_id, count=1
        )
        return pending[0]["times_delivered"] if pending else 1

    @staticmethod
    def _entries(response) -> list[tuple[str, dict]]:
        # [[stream, [(id, fields), ...]]] or [] when nothing arrived
        return response[0][1] if response else []

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
        except Exception:
            # not acked: it stays pending and is retried on the next pending pass
            logger.exception(
                "Handling %s job %s failed (delivery %s)",
                message.event,
                message.job_id,
                deliveries,
            )
            return

        await self._redis.xack(self.stream, self.group, entry_id)

    async def _dead_letter(self, entry_id: str, fields: dict, reason: str, deliveries: int):
        """Copies the job to the dead-letter stream and acks it, in one transaction"""
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(
                self.dead_letter_stream,
                {
                    **fields,
                    "original_id": entry_id,
                    "reason": reason,
                    "deliveries": str(deliveries),
                    "dead_at": datetime.now(UTC).isoformat(),
                },
                maxlen=self._maxlen,
                approximate=True,
            )
            pipe.xack(self.stream, self.group, entry_id)
            await pipe.execute()

        logger.error("Ai job %s moved to %s: %s", entry_id, self.dead_letter_stream, reason)


async def stop_task(task: asyncio.Task | None):
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
