"""Handler for ai:trust:explain."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.enums import LLMTask
from src.schemas.trust import TrustExplainedResult, TrustExplainOutput, TrustExplainRequest
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:trust-explained"


async def handle_trust_explain(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Explains the current trust state and publishes ai:result:trust-explained."""
    try:
        request = TrustExplainRequest.model_validate({**message.payload, "jobId": message.job_id})
        output: TrustExplainOutput = await client.complete(
            LLMTask.TRUST_EXPLAIN,
            load_prompt("trust_explainer"),
            input_prompt(
                "Explain the merchant's current trust state and recommend improvements.",
                request,
            ),
            TrustExplainOutput,
        )
        result = TrustExplainedResult(
            job_id=message.job_id,
            merchant_id=request.merchant_id,
            explanation=output.explanation,
            recommendations=output.recommendations,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
