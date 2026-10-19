import asyncio
import json

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from src.config import Settings
from src.streams import AiRequestConsumer, AiResultPublisher, StreamMessage, stop_task

STREAM: str = "test:ai:requests"
SETTINGS = Settings()


@pytest_asyncio.fixture
async def redis():
    # in-memory redis with streams and consumer groups; no server needed (ci has none)
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def _job(event: str = "ai:dispute:classify", job_id: str = "job-1", **payload) -> dict:
    return {
        "event": event,
        "job_id": job_id,
        "version": "1",
        "payload": json.dumps(payload or {"disputeId": "d-1", "messagesBody": "not received"}),
        "created_at": "2026-10-19T10:00:00+00:00",
    }


class Recorder:
    """Handler that records jobs and fails a set number of times first"""

    def __init__(self, failures: int = 0):
        self.failures = failures
        self.messages: list[StreamMessage] = []

    async def __call__(self, message: StreamMessage):
        self.messages.append(message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("handler failed")


def _consumer(redis, handlers: dict, **kwargs) -> AiRequestConsumer:
    return AiRequestConsumer(
        redis, handlers, SETTINGS, stream=STREAM, block_ms=10, retry_pending_seconds=0, **kwargs
    )


async def _pending(redis, consumer: AiRequestConsumer) -> int:
    return (await redis.xpending(consumer.stream, consumer.group))["pending"]


async def _dead(redis, consumer: AiRequestConsumer) -> list[dict]:
    return [fields for _, fields in await redis.xrange(consumer.dead_letter_stream)]


class TestPublisher:
    @pytest.mark.asyncio
    async def test_publish(self, redis):
        await AiResultPublisher(redis, SETTINGS).publish(
            "ai:result:classified", "job-1", {"disputeId": "d-1", "category": "fraud"}
        )

        entries = await redis.xrange(SETTINGS.AI_RESULT_STREAM)
        fields: dict = entries[0][1]

        assert len(entries) == 1
        assert fields["event"] == "ai:result:classified"
        # the job's id, so the backend can match the result to its job
        assert fields["job_id"] == "job-1"
        assert fields["version"] == "1"
        assert json.loads(fields["payload"]) == {"disputeId": "d-1", "category": "fraud"}


class TestConsumer:
    @pytest.mark.asyncio
    async def test_ensure_group_is_idempotent(self, redis):
        consumer = _consumer(redis, {})

        await consumer.ensure_group()
        await consumer.ensure_group()

        groups = await redis.xinfo_groups(STREAM)
        assert [group["name"] for group in groups] == [consumer.group]

    @pytest.mark.asyncio
    async def test_handles_and_acks(self, redis):
        handler = Recorder()
        consumer = _consumer(redis, {"ai:dispute:classify": handler})
        await consumer.ensure_group()
        await redis.xadd(STREAM, _job())

        assert await consumer.process_new() == 1

        message: StreamMessage = handler.messages[0]
        assert message.event == "ai:dispute:classify"
        assert message.job_id == "job-1"
        assert message.payload == {"disputeId": "d-1", "messagesBody": "not received"}
        assert message.deliveries == 1
        assert await _pending(redis, consumer) == 0

    @pytest.mark.asyncio
    async def test_reads_jobs_added_before_the_group(self, redis):
        await redis.xadd(STREAM, _job())
        handler = Recorder()
        consumer = _consumer(redis, {"ai:dispute:classify": handler})

        await consumer.ensure_group()
        await consumer.process_new()

        assert len(handler.messages) == 1

    @pytest.mark.asyncio
    async def test_failed_handler_is_retried_from_pending(self, redis):
        handler = Recorder(failures=1)
        consumer = _consumer(redis, {"ai:dispute:classify": handler})
        await consumer.ensure_group()
        await redis.xadd(STREAM, _job())

        await consumer.process_new()
        # not acked, so it stays pending
        assert await _pending(redis, consumer) == 1

        assert await consumer.process_pending() == 1

        assert [m.deliveries for m in handler.messages] == [1, 2]
        assert await _pending(redis, consumer) == 0

    @pytest.mark.asyncio
    async def test_replays_pending_after_restart(self, redis):
        consumer = _consumer(redis, {"ai:dispute:classify": Recorder(failures=1)})
        await consumer.ensure_group()
        await redis.xadd(STREAM, _job())
        await consumer.process_new()

        # a new process with the same consumer name picks up the unacked job
        handler = Recorder()
        restarted = _consumer(redis, {"ai:dispute:classify": handler})
        await restarted.process_pending()

        assert [m.job_id for m in handler.messages] == ["job-1"]
        assert await _pending(redis, restarted) == 0

    @pytest.mark.asyncio
    async def test_dead_letters_after_max_deliveries(self, redis):
        handler = Recorder(failures=10)
        consumer = _consumer(redis, {"ai:dispute:classify": handler}, max_deliveries=2)
        await consumer.ensure_group()
        await redis.xadd(STREAM, _job())

        await consumer.process_new()  # delivery 1
        await consumer.process_pending()  # delivery 2
        await consumer.process_pending()  # delivery 3: over the limit

        dead: list[dict] = await _dead(redis, consumer)
        assert len(handler.messages) == 2
        assert dead[0]["reason"] == "max_deliveries_exceeded"
        assert dead[0]["deliveries"] == "3"
        assert dead[0]["job_id"] == "job-1"
        assert await _pending(redis, consumer) == 0

    @pytest.mark.asyncio
    async def test_unhandled_event_is_dead_lettered(self, redis):
        consumer = _consumer(redis, {})
        await consumer.ensure_group()
        entry_id: str = await redis.xadd(STREAM, _job(event="ai:dispute:unknown"))

        await consumer.process_new()

        dead: list[dict] = await _dead(redis, consumer)
        assert dead[0]["reason"] == "unhandled_event"
        assert dead[0]["original_id"] == entry_id
        assert await _pending(redis, consumer) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields",
        [
            {"event": "ai:dispute:classify", "job_id": "job-1"},  # no payload
            {"job_id": "job-1", "payload": "{}"},  # no event
            {"event": "ai:dispute:classify", "job_id": "job-1", "payload": "not json"},
        ],
    )
    async def test_malformed_is_dead_lettered(self, redis, fields: dict):
        handler = Recorder()
        consumer = _consumer(redis, {"ai:dispute:classify": handler})
        await consumer.ensure_group()
        await redis.xadd(STREAM, fields)

        await consumer.process_new()

        assert handler.messages == []
        assert (await _dead(redis, consumer))[0]["reason"] == "malformed"

    @pytest.mark.asyncio
    async def test_run_loop(self, redis):
        handler = Recorder()
        consumer = _consumer(redis, {"ai:dispute:classify": handler})
        task = asyncio.create_task(consumer.run())

        try:
            await redis.xadd(STREAM, _job())
            for _ in range(100):
                if handler.messages:
                    break
                await asyncio.sleep(0.02)
        finally:
            await stop_task(task)

        assert [m.job_id for m in handler.messages] == ["job-1"]
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_handler_can_publish_the_result(self, redis):
        # the shape a real handler takes: do the work, publish with the job's id
        publisher = AiResultPublisher(redis, SETTINGS)

        async def classify(message: StreamMessage):
            await publisher.publish(
                "ai:result:classified",
                message.job_id,
                {"disputeId": message.payload["disputeId"], "category": "fraud"},
            )

        consumer = _consumer(redis, {"ai:dispute:classify": classify})
        await consumer.ensure_group()
        await redis.xadd(STREAM, _job(job_id="job-9"))

        await consumer.process_new()

        (result,) = await redis.xrange(SETTINGS.AI_RESULT_STREAM)
        assert result[1]["job_id"] == "job-9"
        assert result[1]["event"] == "ai:result:classified"
