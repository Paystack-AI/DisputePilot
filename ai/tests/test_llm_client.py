from dataclasses import replace
from typing import ClassVar

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from src.config import Settings
from src.errors import LLMBadRequestError, LLMProviderServerError
from src.llm.base import CompletionRequest, CompletionResponse, LLMProvider
from src.llm.client import LLMClient
from src.llm.health import ProviderHealthStore
from src.schemas.dispute import ClassifierOutput
from src.schemas.enums import LLMTask


class FakeProvider(LLMProvider):
    name: ClassVar[str] = "fake"

    def __init__(self, name: str, responses: list):
        self.name = name
        self.responses = responses
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest, timeout: float) -> CompletionResponse:
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return CompletionResponse(text=response, provider=self.name, model=request.model, raw={})


VALID = (
    '{"category":"fraud","confidence":0.9,"submission_flow":"fraud_flow",'
    '"evidence_strategy":["customer_kyc"],"special_instructions":"submit identity"}'
)


def _settings(**overrides) -> Settings:
    values = {
        "LLM_PROVIDER_ORDER": "gemini,groq",
        "GEMINI_MODEL_CLASSIFIER": "gemini-model",
        "GROQ_MODEL_CLASSIFIER": "groq-model",
        "LLM_MAX_ATTEMPTS": 1,
        "LLM_JSON_RETRY_ATTEMPTS": 1,
        "LLM_RETRY_BACKOFF_SECONDS": 0.0,
    }
    values.update(overrides)
    return replace(Settings(), **values)


@pytest_asyncio.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


def _client(redis, providers: dict[str, FakeProvider], settings: Settings) -> LLMClient:
    health = ProviderHealthStore(redis, "test:health", cooldown_seconds=60, failure_threshold=2)
    return LLMClient(providers, health, settings)


@pytest.mark.asyncio
async def test_fails_over_to_the_next_provider(redis):
    gemini = FakeProvider("gemini", [LLMProviderServerError("down")])
    groq = FakeProvider("groq", [VALID])
    client = _client(redis, {"gemini": gemini, "groq": groq}, _settings())

    output = await client.complete(LLMTask.CLASSIFY, "system", "user", ClassifierOutput)

    assert output.category.value == "fraud"
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1
    assert await redis.get("test:health:gemini:failures") == "1"


@pytest.mark.asyncio
async def test_does_not_fail_over_on_a_bad_request(redis):
    gemini = FakeProvider("gemini", [LLMBadRequestError("bad payload")])
    groq = FakeProvider("groq", [VALID])
    client = _client(redis, {"gemini": gemini, "groq": groq}, _settings())

    with pytest.raises(LLMBadRequestError):
        await client.complete(LLMTask.CLASSIFY, "system", "user", ClassifierOutput)

    assert gemini.calls
    assert groq.calls == []


@pytest.mark.asyncio
async def test_retries_once_with_the_strict_json_suffix(redis):
    gemini = FakeProvider("gemini", ["not json", VALID])
    client = _client(redis, {"gemini": gemini}, _settings(LLM_PROVIDER_ORDER="gemini"))

    output = await client.complete(LLMTask.CLASSIFY, "system", "user", ClassifierOutput)

    assert output.category.value == "fraud"
    assert len(gemini.calls) == 2
    assert "Return ONLY" in gemini.calls[1].user_prompt


@pytest.mark.asyncio
async def test_skips_a_provider_in_cooldown(redis):
    health = ProviderHealthStore(redis, "test:health", cooldown_seconds=60, failure_threshold=1)
    await health.record_failure("gemini")

    gemini = FakeProvider("gemini", [VALID])
    groq = FakeProvider("groq", [VALID])
    client = _client(redis, {"gemini": gemini, "groq": groq}, _settings())

    await client.complete(LLMTask.CLASSIFY, "system", "user", ClassifierOutput)

    assert gemini.calls == []
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_health_cools_down_and_recovers(redis):
    health = ProviderHealthStore(redis, "test:health", cooldown_seconds=60, failure_threshold=2)

    await health.record_failure("gemini")
    assert await health.is_available("gemini") is True

    await health.record_failure("gemini")
    assert await health.is_available("gemini") is False
    assert await health.unavailable_until("gemini") is not None

    await health.record_success("gemini")
    assert await health.is_available("gemini") is True
