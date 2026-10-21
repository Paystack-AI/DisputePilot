"""Handler for ai:dispute:generate-evidence."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.dispute import EvidenceGeneratedResult, EvidenceOutput, EvidenceRequest
from src.schemas.enums import LLMTask
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:evidence-generated"


async def handle_generate_evidence(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Generates the evidence narrative and publishes ai:result:evidence-generated."""
    try:
        request = EvidenceRequest.model_validate({**message.payload, "jobId": message.job_id})
        output: EvidenceOutput = await client.complete(
            LLMTask.GENERATE_EVIDENCE,
            load_prompt("evidence"),
            input_prompt("Write the evidence narrative for the dispute below.", request),
            EvidenceOutput,
        )
        result = EvidenceGeneratedResult(
            jobId=message.job_id,
            dispute_id=request.dispute_id,
            narrative=output.narrative,
            conclusion=output.conclusion,
            missing_evidence=output.missing_evidence,
            evidence_items_referenced=output.evidence_items_referenced,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
