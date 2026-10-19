"""Worker settings from environment variables. The stream names must match the backend's
(AI_REQUEST_STREAM / AI_RESULT_STREAM in backend/app/core/config.py)."""

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


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


def get_settings() -> Settings:
    return Settings()
