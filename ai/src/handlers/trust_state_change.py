"""Handler for ai:trust:state-change."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.enums import LLMTask
from src.schemas.trust import (
    StateChangeSummarizedResult,
    TrustStateChangeOutput,
    TrustStateChangeRequest,
)
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:state-change-summarized"


async def handle_trust_state_change(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Summarizes a trust state change and publishes ai:result:state-change-summarized."""
    try:
        request = TrustStateChangeRequest.model_validate(
            {**message.payload, "jobId": message.job_id}
        )
        output: TrustStateChangeOutput = await client.complete(
            LLMTask.TRUST_STATE_CHANGE,
            load_prompt("trust_explainer"),
            input_prompt("Summarize this trust state change in one sentence.", request),
            TrustStateChangeOutput,
        )
        result = StateChangeSummarizedResult(
            job_id=message.job_id,
            merchant_id=request.merchant_id,
            summary=output.summary,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
