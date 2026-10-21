"""Gemini provider (primary in the ordered chain)."""

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

SAFETY_FINISH_REASONS: frozenset[str] = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)


class GeminiProvider(LLMProvider):
    """Calls the Gemini generateContent REST API."""

    name: ClassVar[str] = "gemini"

    def __init__(self, api_key: str, base_url: str) -> None:
        """Stores the API key and base URL used for Gemini requests."""
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def complete(self, request: CompletionRequest, timeout: float) -> CompletionResponse:
        """Runs one Gemini completion with a per-attempt timeout."""
        url: str = f"{self.base_url}/v1beta/models/{request.model}:generateContent"
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        if request.json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    params={"key": self.api_key},
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
        except Exception as exc:
            raise map_transport_error(self.name, exc) from exc

        raise_for_status(response, self.name)

        try:
            data: dict[str, Any] = response.json()
        except json.JSONDecodeError as exc:
            raise LLMUnparseableOutputError(f"{self.name} returned invalid json") from exc

        candidates: list[dict[str, Any]] = data.get("candidates") or []
        if not candidates:
            feedback: dict[str, Any] = data.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise LLMSafetyBlockError(
                    f"{self.name} blocked the prompt: {feedback.get('blockReason')}"
                )
            raise LLMProviderServerError(f"{self.name} returned no candidates")

        candidate: dict[str, Any] = candidates[0]
        finish_reason: str | None = candidate.get("finishReason")
        if finish_reason in SAFETY_FINISH_REASONS:
            raise LLMSafetyBlockError(f"{self.name} blocked the output: {finish_reason}")

        parts: list[dict[str, Any]] = (candidate.get("content") or {}).get("parts") or []
        text: str = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise LLMProviderServerError(f"{self.name} returned an empty candidate")

        return CompletionResponse(text=text, provider=self.name, model=request.model, raw=data)
