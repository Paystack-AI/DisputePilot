"""Request, result and LLM-output models for the three dispute defense jobs."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.base import JobRequest, JobResult, LLMOutput
from src.schemas.enums import DisputeCategory, SubmissionFlow


class ClassifyRequest(JobRequest):
    """Payload of ai:dispute:classify."""

    dispute_id: str
    # the bank's reason; the backend sends null when the dispute carried no message
    messages_body: str | None = ""
    message_sender: str | None = None
    note: str | None = None
    paystack_category: str | None = None
    transaction_channel: str | None = None
    has_evidence_object: bool = False


class ClassifiedResult(JobResult):
    """Payload of ai:result:classified."""

    dispute_id: str
    category: DisputeCategory
    confidence: float = Field(ge=0.0, le=1.0)
    submission_flow: SubmissionFlow
    evidence_strategy: list[str]
    special_instructions: str | None = None


class ClassifierOutput(LLMOutput):
    """Validated JSON the classifier model must return."""

    category: DisputeCategory
    confidence: float = Field(ge=0.0, le=1.0)
    submission_flow: SubmissionFlow
    evidence_strategy: list[str]
    special_instructions: str | None = None


class EvidenceRequest(JobRequest):
    """Payload of ai:dispute:generate-evidence."""

    dispute_id: str
    # set by the classify step; null only if a dispute reached this step unclassified
    category: DisputeCategory | None = None
    submission_flow: SubmissionFlow | None = None
    transaction: dict[str, Any]
    order: dict[str, Any] | None = None
    fulfillment: list[dict[str, Any]] | dict[str, Any] | None = None
    customer_history: dict[str, Any] | None = None
    reconciliation_status: dict[str, Any] | None = None
    # the backend includes these in the generate payload as well
    reason: str | None = None
    due_at: str | None = None
    supporting_documents: list[dict[str, Any]] = Field(default_factory=list)
    evidence_strategy: list[str] | None = None
    special_instructions: str | None = None


class EvidenceGeneratedResult(JobResult):
    """Payload of ai:result:evidence-generated."""

    dispute_id: str
    narrative: str
    conclusion: str | None = None
    missing_evidence: list[str]
    evidence_items_referenced: list[str]


class EvidenceOutput(LLMOutput):
    """Validated JSON the evidence generator must return."""

    narrative: str
    conclusion: str | None = None
    missing_evidence: list[str]
    evidence_items_referenced: list[str]


class ScoreQualityRequest(JobRequest):
    """Payload of ai:dispute:score-quality."""

    dispute_id: str
    narrative: str
    category: DisputeCategory | None = None
    available_evidence_items: list[str]
    evidence_items_referenced: list[str]


class DimensionScores(BaseModel):
    """Per-dimension quality scores, 0-100."""

    model_config = ConfigDict(extra="forbid")

    completeness: float = Field(ge=0.0, le=100.0)
    evidence_strength: float = Field(ge=0.0, le=100.0)
    formatting: float = Field(ge=0.0, le=100.0)
    customer_context: float = Field(ge=0.0, le=100.0)


class QualityScoredResult(JobResult):
    """Payload of ai:result:quality-scored."""

    dispute_id: str
    overall_score: int = Field(ge=0, le=100)
    dimension_scores: DimensionScores
    suggestions: list[str]
    ready_to_submit: bool


class ScorerOutput(LLMOutput):
    """Validated JSON the quality scorer must return."""

    overall_score: int = Field(ge=0, le=100)
    dimension_scores: DimensionScores
    suggestions: list[str]
    ready_to_submit: bool
