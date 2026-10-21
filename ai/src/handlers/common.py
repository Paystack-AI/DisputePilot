"""Helpers shared by the job handlers."""

from typing import Any

from pydantic import BaseModel

from src.streams import AiResultPublisher, StreamMessage

AI_ERROR: str = "ai:error"


def input_prompt(instruction: str, request: BaseModel) -> str:
    """Builds the user prompt from a task instruction and the validated job input."""
    payload: str = request.model_dump_json(by_alias=True, exclude_none=True, indent=2)
    return f"{instruction}\n\nJob input (JSON):\n{payload}"


def result_payload(model: BaseModel) -> dict[str, Any]:
    """Serializes a result model with the camelCase keys the backend reads."""
    return model.model_dump(by_alias=True, exclude_none=True)


async def publish_error(
    message: StreamMessage,
    publisher: AiResultPublisher,
    exc: Exception,
) -> None:
    """Publishes ai:error so the backend can fall back instead of waiting for a timeout."""
    payload: dict[str, Any] = {
        "jobId": message.job_id,
        "channel": message.event,
        "error": str(exc),
        "retryCount": max(0, message.deliveries - 1),
    }
    dispute_id: Any = message.payload.get("disputeId")
    merchant_id: Any = message.payload.get("merchantId")
    if dispute_id is not None:
        payload["disputeId"] = dispute_id
    if merchant_id is not None:
        payload["merchantId"] = merchant_id

    await publisher.publish(AI_ERROR, message.job_id, payload)
