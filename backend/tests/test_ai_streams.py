import asyncio
import json

import pytest
from redis.asyncio import Redis

from app.api.services.ai_streams import (
    AiResultConsumer,
    AiStreamPublisher,
    StreamMessage,
    stop_task,
)
from app.core.config import get_settings

SETTINGS = get_settings()
STREAM: str = "test:ai:results"


def _result(event: str = "ai:result:classified", job_id: str = "job-1", **payload) -> dict:
    return {
        "event": event,
        "job_id": job_id,
        "version": "1",
        "payload": json.dumps(payload or {"disputeId": "d-1", "category": "fraud"}),
        "created_at": "2026-10-18T10:00:00+00:00",
    }


class Recorder:
    """Handler that records messages and fails a set number of times first"""

    def __init__(self, failures: int = 0):
        self.failures = failures
        self.messages: list[StreamMessage] = []

    async def __call__(self, message: StreamMessage):
        self.messages.append(message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("handler failed")


def _consumer(redis: Redis, handlers: dict, **kwargs) -> AiResultConsumer:
    return AiResultConsumer(
        redis, handlers, stream=STREAM, block_ms=10, retry_pending_seconds=0, **kwargs
    )


async def _pending(redis: Redis, consumer: AiResultConsumer) -> int:
    return (await redis.xpending(consumer.stream, consumer.group))["pending"]


async def _dead(redis: Redis, consumer: AiResultConsumer) -> list[dict]:
    return [fields for _, fields in await redis.xrange(consumer.dead_letter_stream)]


class TestPublisher:
    @pytest.mark.asyncio
    async def test_publish(self, test_redis_client: Redis):
        job_id: str = await AiStreamPublisher(test_redis_client).publish(
            "ai:dispute:classify", {"disputeId": "d-1"}
        )

        entries = await test_redis_client.xrange(SETTINGS.AI_REQUEST_STREAM)
        fields: dict = entries[0][1]

        assert len(entries) == 1
        assert fields["event"] == "ai:dispute:classify"
        assert fields["job_id"] == job_id
        assert fields["version"] == "1"
        assert json.loads(fields["payload"]) == {"disputeId": "d-1"}

    @pytest.mark.asyncio
    async def test_given_job_id(self, test_redis_client: Redis):
        job_id: str = await AiStreamPublisher(test_redis_client).publish(
            "ai:trust:explain", {}, job_id="job-42"
        )

        assert job_id == "job-42"


class TestConsumer:
    @pytest.mark.asyncio
    async def test_ensure_group_is_idempotent(self, test_redis_client: Redis):
        consumer = _consumer(test_redis_client, {})

        await consumer.ensure_group()
        await consumer.ensure_group()

        groups = await test_redis_client.xinfo_groups(STREAM)
        assert [group["name"] for group in groups] == [consumer.group]

    @pytest.mark.asyncio
    async def test_handles_and_acks(self, test_redis_client: Redis):
        handler = Recorder()
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler})
        await consumer.ensure_group()
        await test_redis_client.xadd(STREAM, _result())

        assert await consumer.process_new() == 1

        message: StreamMessage = handler.messages[0]
        assert message.event == "ai:result:classified"
        assert message.job_id == "job-1"
        assert message.payload == {"disputeId": "d-1", "category": "fraud"}
        assert message.deliveries == 1
        assert await _pending(test_redis_client, consumer) == 0

    @pytest.mark.asyncio
    async def test_reads_results_added_before_the_group(self, test_redis_client: Redis):
        await test_redis_client.xadd(STREAM, _result())
        handler = Recorder()
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler})

        await consumer.ensure_group()
        await consumer.process_new()

        assert len(handler.messages) == 1

    @pytest.mark.asyncio
    async def test_failed_handler_is_retried_from_pending(self, test_redis_client: Redis):
        handler = Recorder(failures=1)
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler})
        await consumer.ensure_group()
        await test_redis_client.xadd(STREAM, _result())

        await consumer.process_new()
        # not acked, so it stays pending
        assert await _pending(test_redis_client, consumer) == 1

        assert await consumer.process_pending() == 1

        assert [m.deliveries for m in handler.messages] == [1, 2]
        assert await _pending(test_redis_client, consumer) == 0

    @pytest.mark.asyncio
    async def test_replays_pending_after_restart(self, test_redis_client: Redis):
        consumer = _consumer(test_redis_client, {"ai:result:classified": Recorder(failures=1)})
        await consumer.ensure_group()
        await test_redis_client.xadd(STREAM, _result())
        await consumer.process_new()

        # a new process with the same consumer name picks up the unacked result
        handler = Recorder()
        restarted = _consumer(test_redis_client, {"ai:result:classified": handler})
        await restarted.process_pending()

        assert [m.job_id for m in handler.messages] == ["job-1"]
        assert await _pending(test_redis_client, restarted) == 0

    @pytest.mark.asyncio
    async def test_dead_letters_after_max_deliveries(self, test_redis_client: Redis):
        handler = Recorder(failures=10)
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler}, max_deliveries=2)
        await consumer.ensure_group()
        await test_redis_client.xadd(STREAM, _result())

        await consumer.process_new()  # delivery 1
        await consumer.process_pending()  # delivery 2
        await consumer.process_pending()  # delivery 3: over the limit

        dead: list[dict] = await _dead(test_redis_client, consumer)
        assert len(handler.messages) == 2
        assert dead[0]["reason"] == "max_deliveries_exceeded"
        assert dead[0]["deliveries"] == "3"
        assert dead[0]["job_id"] == "job-1"
        assert await _pending(test_redis_client, consumer) == 0

    @pytest.mark.asyncio
    async def test_unhandled_event_is_dead_lettered(self, test_redis_client: Redis):
        consumer = _consumer(test_redis_client, {})
        await consumer.ensure_group()
        entry_id: str = await test_redis_client.xadd(STREAM, _result(event="ai:result:unknown"))

        await consumer.process_new()

        dead: list[dict] = await _dead(test_redis_client, consumer)
        assert dead[0]["reason"] == "unhandled_event"
        assert dead[0]["original_id"] == entry_id
        assert await _pending(test_redis_client, consumer) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields",
        [
            {"event": "ai:result:classified", "job_id": "job-1"},  # no payload
            {"job_id": "job-1", "payload": "{}"},  # no event
            {"event": "ai:result:classified", "job_id": "job-1", "payload": "not json"},
        ],
    )
    async def test_malformed_is_dead_lettered(self, test_redis_client: Redis, fields: dict):
        handler = Recorder()
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler})
        await consumer.ensure_group()
        await test_redis_client.xadd(STREAM, fields)

        await consumer.process_new()

        assert handler.messages == []
        assert (await _dead(test_redis_client, consumer))[0]["reason"] == "malformed"

    @pytest.mark.asyncio
    async def test_run_loop(self, test_redis_client: Redis):
        handler = Recorder()
        consumer = _consumer(test_redis_client, {"ai:result:classified": handler})
        task = asyncio.create_task(consumer.run())

        try:
            await test_redis_client.xadd(STREAM, _result())
            for _ in range(100):
                if handler.messages:
                    break
                await asyncio.sleep(0.02)
        finally:
            await stop_task(task)

        assert [m.job_id for m in handler.messages] == ["job-1"]
        assert task.cancelled()
