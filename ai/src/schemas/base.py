"""Base models for job payloads and validated LLM output."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class JobRequest(BaseModel):
    """Fields shared by every backend -> ai job payload.

    The backend writes camelCase payload keys (jobId, disputeId, ...); snake_case
    field names are also accepted.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    job_id: str


class JobResult(BaseModel):
    """Fields shared by every ai -> backend result payload."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    job_id: str


class LLMOutput(BaseModel):
    """Base for a model that an LLM response is validated against."""

    model_config = ConfigDict(extra="forbid")
