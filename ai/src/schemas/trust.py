"""Request, result and LLM-output models for the three trust jobs."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.schemas.base import JobRequest, JobResult, LLMOutput
from src.schemas.enums import TrustState


class TrustRecommendation(BaseModel):
    """One actionable recommendation returned by the trust explainer."""

    model_config = ConfigDict(extra="forbid")

    action: str
    impact_description: str
    affected_signal: str


class TrustExplainRequest(JobRequest):
    """Payload of ai:trust:explain."""

    merchant_id: str
    current_state: TrustState
    # null when there is nothing to measure yet (e.g. no resolved disputes)
    signals: dict[str, float | None]
    # payments_30d and days_on_platform: below the minimum the state is new
    sample: dict[str, int] | None = None
    policy_thresholds: dict[str, Any]


class TrustExplainedResult(JobResult):
    """Payload of ai:result:trust-explained."""

    merchant_id: str
    explanation: str
    recommendations: list[TrustRecommendation]


class TrustExplainOutput(LLMOutput):
    """Validated JSON the trust explainer must return."""

    explanation: str
    recommendations: list[TrustRecommendation]


class TrustRecommendRequest(JobRequest):
    """Payload of ai:trust:recommend."""

    merchant_id: str
    weakest_signals: list[str]
    recent_trends: dict[str, Any]


class TrustRecommendResult(JobResult):
    """Result of ai:trust:recommend, published on ai:result:trust-explained."""

    merchant_id: str
    explanation: str
    recommendations: list[TrustRecommendation]


class TrustRecommendOutput(LLMOutput):
    """Validated JSON the trust recommender must return."""

    explanation: str | None = None
    recommendations: list[TrustRecommendation]


class TrustStateChangeRequest(JobRequest):
    """Payload of ai:trust:state-change."""

    merchant_id: str
    previous_state: TrustState
    new_state: TrustState
    signal_diff: dict[str, Any]


class StateChangeSummarizedResult(JobResult):
    """Payload of ai:result:state-change-summarized."""

    merchant_id: str
    summary: str


class TrustStateChangeOutput(LLMOutput):
    """Validated JSON the state-change summarizer must return."""

    summary: str
