"""Common interface shared by every LLM provider."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from src.errors import (
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMNetworkError,
    LLMProviderServerError,
    LLMRateLimitError,
    LLMSafetyBlockError,
    LLMTimeoutError,
)


@dataclass(frozen=True)
class CompletionRequest:
    """One provider call, already resolved to a model and generation settings."""

    model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    max_tokens: int
    json_mode: bool = True


@dataclass(frozen=True)
class CompletionResponse:
    """Raw text and metadata returned by a provider."""

    text: str
    provider: str
    model: str
    raw: dict[str, Any]


class LLMProvider(ABC):
    """Interface a Gemini or Groq provider implements."""

    name: ClassVar[str]

    @abstractmethod
    def __init__(self, api_key: str, base_url: str) -> None:
        """Stores the credentials and endpoint used by this provider."""
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def complete(self, request: CompletionRequest, timeout: float) -> CompletionResponse:
        """Runs one completion attempt and returns its raw response."""
        raise NotImplementedError


def _body_text(response: httpx.Response) -> str:
    """A short, loggable description of a provider error body."""
    try:
        body: Any = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    return json.dumps(body)[:500]


def raise_for_status(response: httpx.Response, provider: str) -> None:
    """Maps an HTTP failure to the matching LLM error category."""
    if response.is_success:
        return

    status: int = response.status_code
    body: str = _body_text(response).lower()

    if status == 429:
        raise LLMRateLimitError(f"{provider} rate limit: {_body_text(response)}")
    if status in (401, 403):
        raise LLMAuthenticationError(f"{provider} rejected the api key: {_body_text(response)}")
    if status >= 500:
        raise LLMProviderServerError(f"{provider} server error ({status}): {_body_text(response)}")
    if status in (400, 404, 422):
        if "safety" in body or "content_policy" in body or "content filter" in body:
            raise LLMSafetyBlockError(f"{provider} blocked the request: {_body_text(response)}")
        raise LLMBadRequestError(f"{provider} bad request ({status}): {_body_text(response)}")

    raise LLMBadRequestError(f"{provider} rejected the request ({status}): {_body_text(response)}")


def map_transport_error(provider: str, exc: Exception) -> Exception:
    """Maps an httpx transport failure to the retryable LLM error category."""
    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError(f"{provider} timed out: {exc}")
    if isinstance(exc, httpx.RequestError):
        return LLMNetworkError(f"{provider} network error: {exc}")
    return exc
