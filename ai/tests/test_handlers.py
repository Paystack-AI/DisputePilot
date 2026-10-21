import json
from dataclasses import replace

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from src.config import Settings
from src.errors import LLMRateLimitError
from src.handlers.classifier import handle_classify
from src.schemas.dispute import ClassifierOutput
from src.schemas.enums import DisputeCategory, SubmissionFlow
from src.streams import AiResultPublisher, StreamMessage


class FakeClient:
    def __init__(self, output=None, error: Exception | None = None):
        self.output = output
        self.error = error

    async def complete(self, task, system_prompt, user_prompt, output_model):
        if self.error:
            raise self.error
        return self.output


def _message(**payload) -> StreamMessage:
    return StreamMessage(
        id="1-0",
        event="ai:dispute:classify",
        job_id="job-1",
        version="1",
        payload={"disputeId": "d-1", **payload},
        created_at="2026-10-19T10:00:00+00:00",
        deliveries=1,
    )


@pytest_asyncio.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_classifier_publishes_a_camel_case_result(redis):
    settings = replace(Settings(), AI_RESULT_STREAM="test:results")
    publisher = AiResultPublisher(redis, settings)
    output = ClassifierOutput(
        category=DisputeCategory.FRAUD,
        confidence=0.91,
        submission_flow=SubmissionFlow.FRAUD_FLOW,
        evidence_strategy=["customer_kyc"],
        special_instructions="submit identity",
    )

    await handle_classify(
        _message(messagesBody="unauthorized card use"), FakeClient(output), publisher
    )

    ((_, fields),) = await redis.xrange("test:results")
    payload = json.loads(fields["payload"])
    assert fields["event"] == "ai:result:classified"
    assert fields["job_id"] == "job-1"
    assert payload["jobId"] == "job-1"
    assert payload["disputeId"] == "d-1"
    assert payload["category"] == "fraud"
    assert payload["submissionFlow"] == "fraud_flow"


@pytest.mark.asyncio
async def test_classifier_publishes_ai_error_instead_of_raising(redis):
    settings = replace(Settings(), AI_RESULT_STREAM="test:results")
    publisher = AiResultPublisher(redis, settings)

    await handle_classify(
        _message(messagesBody="unauthorized card use"),
        FakeClient(error=LLMRateLimitError("rate limited")),
        publisher,
    )

    ((_, fields),) = await redis.xrange("test:results")
    payload = json.loads(fields["payload"])
    assert fields["event"] == "ai:error"
    assert payload["jobId"] == "job-1"
    assert payload["disputeId"] == "d-1"
    assert payload["channel"] == "ai:dispute:classify"
    assert "rate limited" in payload["error"]
