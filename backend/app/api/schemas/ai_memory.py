from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryCorrection(BaseModel):
    content: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)


class MemoryMutationResponse(BaseModel):
    id: UUID
    deleted: bool = False
