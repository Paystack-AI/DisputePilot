"""Handler for ai:dispute:classify."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.dispute import ClassifiedResult, ClassifierOutput, ClassifyRequest
from src.schemas.enums import LLMTask
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:classified"


async def handle_classify(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Classifies a dispute and publishes ai:result:classified."""
    try:
        request = ClassifyRequest.model_validate({**message.payload, "jobId": message.job_id})
        output: ClassifierOutput = await client.complete(
            LLMTask.CLASSIFY,
            load_prompt("classifier"),
            input_prompt("Classify the dispute described below.", request),
            ClassifierOutput,
        )
        result = ClassifiedResult(
            jobId=message.job_id,
            dispute_id=request.dispute_id,
            category=output.category,
            confidence=output.confidence,
            submission_flow=output.submission_flow,
            evidence_strategy=output.evidence_strategy,
            special_instructions=output.special_instructions,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
