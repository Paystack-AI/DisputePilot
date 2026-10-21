"""Maps each backend job event to its handler."""

from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from src.config import Settings
from src.handlers.classifier import handle_classify
from src.handlers.evidence_generator import handle_generate_evidence
from src.handlers.quality_scorer import handle_score_quality
from src.handlers.trust_explainer import handle_trust_explain
from src.handlers.trust_recommender import handle_trust_recommend
from src.handlers.trust_state_change import handle_trust_state_change
from src.llm.client import LLMClient
from src.llm.gemini import GeminiProvider
from src.llm.groq import GroqProvider
from src.llm.health import ProviderHealthStore
from src.streams import AiResultPublisher, Handler, StreamMessage

CLASSIFY: str = "ai:dispute:classify"
GENERATE_EVIDENCE: str = "ai:dispute:generate-evidence"
SCORE_QUALITY: str = "ai:dispute:score-quality"
TRUST_EXPLAIN: str = "ai:trust:explain"
TRUST_RECOMMEND: str = "ai:trust:recommend"
TRUST_STATE_CHANGE: str = "ai:trust:state-change"


def _bind(
    handler: Callable[[StreamMessage, LLMClient, AiResultPublisher], Awaitable[None]],
    client: LLMClient,
    publisher: AiResultPublisher,
) -> Handler:
    async def bound(message: StreamMessage) -> None:
        await handler(message, client, publisher)

    return bound


def build_handlers(async_redis: Redis, settings: Settings) -> dict[str, Handler]:
    """Builds the event -> handler map with the shared LLM client and result publisher."""
    providers = {}
    if settings.GEMINI_API_KEY:
        providers[GeminiProvider.name] = GeminiProvider(
            settings.GEMINI_API_KEY, settings.GEMINI_BASE_URL
        )
    if settings.GROQ_API_KEY:
        providers[GroqProvider.name] = GroqProvider(settings.GROQ_API_KEY, settings.GROQ_BASE_URL)

    health = ProviderHealthStore(
        async_redis,
        settings.LLM_HEALTH_KEY_PREFIX,
        settings.LLM_PROVIDER_COOLDOWN_SECONDS,
        settings.LLM_PROVIDER_FAILURE_THRESHOLD,
    )
    client = LLMClient(providers, health, settings)
    publisher = AiResultPublisher(async_redis, settings)

    return {
        CLASSIFY: _bind(handle_classify, client, publisher),
        GENERATE_EVIDENCE: _bind(handle_generate_evidence, client, publisher),
        SCORE_QUALITY: _bind(handle_score_quality, client, publisher),
        TRUST_EXPLAIN: _bind(handle_trust_explain, client, publisher),
        TRUST_RECOMMEND: _bind(handle_trust_recommend, client, publisher),
        TRUST_STATE_CHANGE: _bind(handle_trust_state_change, client, publisher),
    }
