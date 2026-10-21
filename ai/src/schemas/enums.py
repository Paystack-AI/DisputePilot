"""Shared values for job payloads and validated LLM output."""

from enum import StrEnum


class DisputeCategory(StrEnum):
    """Dispute categories the classifier may return."""

    CHARGEBACK_NO_VALUE = "chargeback_no_value"
    CHARGEBACK_NOT_AS_DESCRIBED = "chargeback_not_as_described"
    FRAUD = "fraud"
    ADMIN_ERROR = "admin_error"
    UNKNOWN = "unknown"


class SubmissionFlow(StrEnum):
    """Paystack submission path chosen by the classifier."""

    CHARGEBACK_FLOW = "chargeback_flow"
    FRAUD_FLOW = "fraud_flow"


class TrustState(StrEnum):
    """TrustLayer states used by the trust tasks."""

    VERIFIED = "verified"
    BUILDING = "building"
    NEW = "new"
    REVIEW = "review"


class LLMTask(StrEnum):
    """Tasks that select a model, temperature and max tokens from config."""

    CLASSIFY = "classifier"
    GENERATE_EVIDENCE = "evidence"
    SCORE_QUALITY = "scorer"
    TRUST_EXPLAIN = "trust_explain"
    TRUST_RECOMMEND = "trust_recommend"
    TRUST_STATE_CHANGE = "trust_state_change"
