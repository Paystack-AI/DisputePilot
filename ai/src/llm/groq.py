"""Groq provider (fallback in the ordered chain)."""

import json
from typing import Any, ClassVar

import httpx

from src.errors import LLMProviderServerError, LLMSafetyBlockError, LLMUnparseableOutputError
from src.llm.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    map_transport_error,
    raise_for_status,
)

SAFETY_FINISH_REASONS: frozenset[str] = frozenset({"content_filter"})


class GroqProvider(LLMProvider):
    """Calls the Groq OpenAI-compatible chat completions REST API."""

    name: ClassVar[str] = "groq"

    def __init__(self, api_key: str, base_url: str) -> None:
        """Stores the API key and base URL used for Groq requests."""
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def complete(self, request: CompletionRequest, timeout: float) -> CompletionResponse:
        """Runs one Groq completion with a per-attempt timeout."""
        url: str = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except Exception as exc:
            raise map_transport_error(self.name, exc) from exc

        raise_for_status(response, self.name)

        try:
            data: dict[str, Any] = response.json()
        except json.JSONDecodeError as exc:
            raise LLMUnparseableOutputError(f"{self.name} returned invalid json") from exc

        choices: list[dict[str, Any]] = data.get("choices") or []
        if not choices:
            raise LLMProviderServerError(f"{self.name} returned no choices")

        choice: dict[str, Any] = choices[0]
        finish_reason: str | None = choice.get("finish_reason")
        if finish_reason in SAFETY_FINISH_REASONS:
            raise LLMSafetyBlockError(f"{self.name} blocked the output: {finish_reason}")

        text: str = ((choice.get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMProviderServerError(f"{self.name} returned an empty message")

        return CompletionResponse(text=text, provider=self.name, model=request.model, raw=data)
