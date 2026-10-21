"""Worker settings from environment variables. The stream names must match the backend's
(AI_REQUEST_STREAM / AI_RESULT_STREAM in backend/app/core/config.py)."""

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    REDIS_URL: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )

    # backend -> ai: jobs this worker consumes
    AI_REQUEST_STREAM: str = field(
        default_factory=lambda: os.getenv("AI_REQUEST_STREAM", "ai:stream:requests")
    )
    # ai -> backend: results this worker adds
    AI_RESULT_STREAM: str = field(
        default_factory=lambda: os.getenv("AI_RESULT_STREAM", "ai:stream:results")
    )
    AI_REQUEST_GROUP: str = field(default_factory=lambda: os.getenv("AI_REQUEST_GROUP", "ai"))
    # stable across restarts so a restarted worker replays its own pending jobs; give each
    # worker instance its own name if more than one runs
    AI_REQUEST_CONSUMER: str = field(
        default_factory=lambda: os.getenv("AI_REQUEST_CONSUMER", "ai-1")
    )
    # approximate cap on each stream's length; older (acked) entries are trimmed
    AI_STREAM_MAXLEN: int = field(default_factory=lambda: _int("AI_STREAM_MAXLEN", 10_000))
    # deliveries after which a failing job is moved to the dead-letter stream
    AI_REQUEST_MAX_DELIVERIES: int = field(
        default_factory=lambda: _int("AI_REQUEST_MAX_DELIVERIES", 5)
    )
    # how long one read blocks waiting for new jobs, and how often pending ones retry
    AI_REQUEST_BLOCK_MS: int = field(default_factory=lambda: _int("AI_REQUEST_BLOCK_MS", 5_000))
    AI_REQUEST_RETRY_PENDING_SECONDS: int = field(
        default_factory=lambda: _int("AI_REQUEST_RETRY_PENDING_SECONDS", 60)
    )

    # ------------------------------ llm providers ------------------------------ #
    # keys; empty means the provider is not configured and is skipped
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GROQ_API_KEY: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    GEMINI_BASE_URL: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"
        )
    )
    GROQ_BASE_URL: str = field(
        default_factory=lambda: os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    )
    # ordered provider chain, comma separated; e.g. "gemini,groq"
    LLM_PROVIDER_ORDER: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER_ORDER", "gemini,groq")
    )

    # model ids per provider and task (never hard-coded in the client)
    GEMINI_MODEL_CLASSIFIER: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_CLASSIFIER", "gemini-3.8-flash")
    )
    GEMINI_MODEL_EVIDENCE: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_EVIDENCE", "gemini-3.8-flash")
    )
    GEMINI_MODEL_SCORER: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_SCORER", "gemini-3.8-flash")
    )
    GEMINI_MODEL_TRUST_EXPLAIN: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_TRUST_EXPLAIN", "gemini-3.8-flash")
    )
    GEMINI_MODEL_TRUST_RECOMMEND: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_TRUST_RECOMMEND", "gemini-3.8-flash")
    )
    GEMINI_MODEL_TRUST_STATE_CHANGE: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_TRUST_STATE_CHANGE", "gemini-3.8-flash")
    )
    GROQ_MODEL_CLASSIFIER: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_CLASSIFIER", "openai/gpt-oss-120b")
    )
    GROQ_MODEL_EVIDENCE: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_EVIDENCE", "openai/gpt-oss-120b")
    )
    GROQ_MODEL_SCORER: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_SCORER", "openai/gpt-oss-120b")
    )
    GROQ_MODEL_TRUST_EXPLAIN: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_TRUST_EXPLAIN", "openai/gpt-oss-120b")
    )
    GROQ_MODEL_TRUST_RECOMMEND: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_TRUST_RECOMMEND", "openai/gpt-oss-120b")
    )
    GROQ_MODEL_TRUST_STATE_CHANGE: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL_TRUST_STATE_CHANGE", "openai/gpt-oss-120b")
    )

    # per-task generation settings
    CLASSIFIER_TEMPERATURE: float = field(
        default_factory=lambda: _float("CLASSIFIER_TEMPERATURE", 0.1)
    )
    EVIDENCE_TEMPERATURE: float = field(default_factory=lambda: _float("EVIDENCE_TEMPERATURE", 0.3))
    SCORER_TEMPERATURE: float = field(default_factory=lambda: _float("SCORER_TEMPERATURE", 0.1))
    TRUST_TEMPERATURE: float = field(default_factory=lambda: _float("TRUST_TEMPERATURE", 0.1))
    CLASSIFIER_MAX_TOKENS: int = field(default_factory=lambda: _int("CLASSIFIER_MAX_TOKENS", 500))
    EVIDENCE_MAX_TOKENS: int = field(default_factory=lambda: _int("EVIDENCE_MAX_TOKENS", 2000))
    SCORER_MAX_TOKENS: int = field(default_factory=lambda: _int("SCORER_MAX_TOKENS", 500))
    TRUST_MAX_TOKENS: int = field(default_factory=lambda: _int("TRUST_MAX_TOKENS", 500))

    # per-attempt timeout; one attempt is a single provider request
    LLM_ATTEMPT_TIMEOUT_SECONDS: float = field(
        default_factory=lambda: _float("LLM_ATTEMPT_TIMEOUT_SECONDS", 20.0)
    )
    # attempts per provider before failing over
    LLM_MAX_ATTEMPTS: int = field(default_factory=lambda: _int("LLM_MAX_ATTEMPTS", 2))
    LLM_RETRY_BACKOFF_SECONDS: float = field(
        default_factory=lambda: _float("LLM_RETRY_BACKOFF_SECONDS", 2.0)
    )
    # extra attempts after unparseable json, with a stricter prompt suffix
    LLM_JSON_RETRY_ATTEMPTS: int = field(default_factory=lambda: _int("LLM_JSON_RETRY_ATTEMPTS", 1))

    # provider health/cooldown state shared by worker instances through redis
    LLM_HEALTH_KEY_PREFIX: str = field(
        default_factory=lambda: os.getenv("LLM_HEALTH_KEY_PREFIX", "ai:llm:health")
    )
    LLM_PROVIDER_COOLDOWN_SECONDS: int = field(
        default_factory=lambda: _int("LLM_PROVIDER_COOLDOWN_SECONDS", 60)
    )
    LLM_PROVIDER_FAILURE_THRESHOLD: int = field(
        default_factory=lambda: _int("LLM_PROVIDER_FAILURE_THRESHOLD", 3)
    )


def get_settings() -> Settings:
    return Settings()
