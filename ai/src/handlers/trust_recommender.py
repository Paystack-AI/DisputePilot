"""Handler for ai:trust:recommend."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.enums import LLMTask
from src.schemas.trust import TrustRecommendOutput, TrustRecommendRequest, TrustRecommendResult
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:trust-explained"
DEFAULT_EXPLANATION: str = "Prioritized actions based on your weakest trust signals."


async def handle_trust_recommend(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Produces trust improvement actions and publishes ai:result:trust-explained."""
    try:
        request = TrustRecommendRequest.model_validate({**message.payload, "jobId": message.job_id})
        output: TrustRecommendOutput = await client.complete(
            LLMTask.TRUST_RECOMMEND,
            load_prompt("trust_recommender"),
            input_prompt(
                "Recommend the most impactful actions the merchant can take next.",
                request,
            ),
            TrustRecommendOutput,
        )
        result = TrustRecommendResult(
            job_id=message.job_id,
            merchant_id=request.merchant_id,
            explanation=output.explanation or DEFAULT_EXPLANATION,
            recommendations=output.recommendations,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
