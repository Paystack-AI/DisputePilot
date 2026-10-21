"""Ordered provider chain with failover, timeouts, JSON retry and output validation."""

import asyncio
import json
from dataclasses import replace
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.config import Settings
from src.errors import (
    LLMAllProvidersFailedError,
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMConfigurationError,
    LLMError,
    LLMSafetyBlockError,
    LLMUnparseableOutputError,
)
from src.llm.base import CompletionRequest, CompletionResponse, LLMProvider, map_transport_error
from src.llm.health import ProviderHealthStore
from src.schemas.enums import LLMTask

T = TypeVar("T", bound=BaseModel)

STRICT_JSON_SUFFIX: str = (
    "\n\nYour previous response was not valid JSON. Return ONLY a single JSON object "
    "matching the requested schema. Do not use markdown fences or add any text before or "
    "after the JSON."
)


class LLMClient:
    """Runs a task through the configured provider chain and validates the result."""

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        health: ProviderHealthStore,
        settings: Settings,
    ) -> None:
        """Stores the available providers and the shared health store."""
        self._providers = providers
        self._health = health
        self._settings = settings

    async def complete(
        self,
        task: LLMTask,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        """Returns a validated output object, failing over between providers as needed."""
        chain: list[LLMProvider] = self._provider_chain()
        if not chain:
            raise LLMConfigurationError("no llm provider is configured")

        temperature, max_tokens = self._generation_settings(task)
        last_error: LLMError | None = None

        for provider in chain:
            if not await self._health.is_available(provider.name):
                continue

            try:
                request = CompletionRequest(
                    model=self._model_for(provider.name, task),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                result: T = await self._complete_with_provider(provider, request, output_model)
            except (LLMSafetyBlockError, LLMAuthenticationError, LLMBadRequestError) as exc:
                # retrying another provider with the same key/payload is not useful
                raise exc
            except LLMConfigurationError as exc:
                # this provider has no model for the task; the next one may
                last_error = exc
                continue
            except LLMError as exc:
                if not exc.failover:
                    raise
                await self._health.record_failure(provider.name)
                last_error = exc
                continue

            await self._health.record_success(provider.name)
            return result

        raise LLMAllProvidersFailedError(
            f"all providers failed for {task.value}: {last_error or 'no provider available'}"
        )

    def _provider_chain(self) -> list[LLMProvider]:
        """Returns providers in configured order, skipping providers without a key."""
        names: list[str] = [
            name.strip().lower()
            for name in self._settings.LLM_PROVIDER_ORDER.split(",")
            if name.strip()
        ]
        return [self._providers[name] for name in names if name in self._providers]

    def _model_for(self, provider: str, task: LLMTask) -> str:
        """Reads the model id for this provider and task from config."""
        field: str = f"{provider.upper()}_MODEL_{task.value.upper()}"
        model: str = getattr(self._settings, field, "")
        if not model:
            raise LLMConfigurationError(f"{field} is not set")
        return model

    def _generation_settings(self, task: LLMTask) -> tuple[float, int]:
        """Returns (temperature, max_tokens) for this task from config."""
        settings: Settings = self._settings
        if task == LLMTask.CLASSIFY:
            return settings.CLASSIFIER_TEMPERATURE, settings.CLASSIFIER_MAX_TOKENS
        if task == LLMTask.GENERATE_EVIDENCE:
            return settings.EVIDENCE_TEMPERATURE, settings.EVIDENCE_MAX_TOKENS
        if task == LLMTask.SCORE_QUALITY:
            return settings.SCORER_TEMPERATURE, settings.SCORER_MAX_TOKENS
        return settings.TRUST_TEMPERATURE, settings.TRUST_MAX_TOKENS

    def _classify_error(self, provider: str, exc: Exception) -> LLMError:
        """Maps an HTTP/transport failure to the matching LLMError category."""
        if isinstance(exc, LLMError):
            return exc
        mapped = map_transport_error(provider, exc)
        if isinstance(mapped, LLMError):
            return mapped
        return LLMError(f"{provider} request failed: {exc}")

    async def _complete_with_provider(
        self,
        provider: LLMProvider,
        request: CompletionRequest,
        output_model: type[T],
    ) -> T:
        """Calls one provider with retries, then parses and validates its output."""
        attempts: int = 0
        json_retries: int = 0
        prompt: str = request.user_prompt
        max_attempts: int = max(self._settings.LLM_MAX_ATTEMPTS, 1)
        max_calls: int = max_attempts + max(self._settings.LLM_JSON_RETRY_ATTEMPTS, 0)
        last_error: LLMError | None = None

        while attempts < max_calls:
            attempts += 1
            attempt_request = replace(request, user_prompt=prompt)
            try:
                response: CompletionResponse = await provider.complete(
                    attempt_request, self._settings.LLM_ATTEMPT_TIMEOUT_SECONDS
                )
            except Exception as exc:
                error: LLMError = self._classify_error(provider.name, exc)
                last_error = error
                if not error.retryable or attempts >= max_attempts:
                    raise error from exc
                delay: float = self._settings.LLM_RETRY_BACKOFF_SECONDS * (2 ** (attempts - 1))
                await asyncio.sleep(delay)
                continue

            try:
                return self._parse_output(response, output_model)
            except LLMUnparseableOutputError as exc:
                last_error = exc
                if json_retries >= self._settings.LLM_JSON_RETRY_ATTEMPTS:
                    raise
                json_retries += 1
                prompt = self._with_strict_json_suffix(prompt)
                continue

        raise last_error or LLMUnparseableOutputError(
            f"{provider.name} returned no usable response"
        )

    def _parse_output(self, response: CompletionResponse, output_model: type[T]) -> T:
        """Parses JSON text and validates it against the task's output model."""
        text: str = response.text.strip()
        if text.startswith("```"):
            lines: list[str] = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start: int = text.find("{")
            end: int = text.rfind("}")
            if start == -1 or end <= start:
                raise LLMUnparseableOutputError(
                    f"{response.provider} returned unparseable json"
                ) from None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMUnparseableOutputError(
                    f"{response.provider} returned unparseable json"
                ) from exc

        try:
            return output_model.model_validate(data)
        except ValidationError as exc:
            raise LLMUnparseableOutputError(
                f"{response.provider} output did not match {output_model.__name__}: {exc}"
            ) from exc

    def _with_strict_json_suffix(self, user_prompt: str) -> str:
        """Appends the stricter JSON-only reminder after an unparseable response."""
        return f"{user_prompt}{STRICT_JSON_SUFFIX}"
