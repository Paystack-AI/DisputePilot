"""Handler for ai:dispute:score-quality."""

from src.handlers.common import input_prompt, publish_error, result_payload
from src.llm.client import LLMClient
from src.prompts.loader import load_prompt
from src.schemas.dispute import QualityScoredResult, ScoreQualityRequest, ScorerOutput
from src.schemas.enums import LLMTask
from src.streams import AiResultPublisher, StreamMessage

EVENT: str = "ai:result:quality-scored"


async def handle_score_quality(
    message: StreamMessage,
    client: LLMClient,
    publisher: AiResultPublisher,
) -> None:
    """Scores the evidence narrative and publishes ai:result:quality-scored."""
    try:
        request = ScoreQualityRequest.model_validate({**message.payload, "jobId": message.job_id})
        output: ScorerOutput = await client.complete(
            LLMTask.SCORE_QUALITY,
            load_prompt("scorer"),
            input_prompt("Score the evidence response below.", request),
            ScorerOutput,
        )
        result = QualityScoredResult(
            jobId=message.job_id,
            dispute_id=request.dispute_id,
            overall_score=output.overall_score,
            dimension_scores=output.dimension_scores,
            suggestions=output.suggestions,
            ready_to_submit=output.ready_to_submit,
        )
        await publisher.publish(EVENT, message.job_id, result_payload(result))
    except Exception as exc:
        await publish_error(message, publisher, exc)
