from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.api.schemas.pagination import PageMeta

T = TypeVar("T", bound=BaseModel)


class SuccessResponse(BaseModel, Generic[T]):
    data: T


class ListSuccessResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class Error(BaseModel):
    code: str
    message: str
    request_id: UUID
    details: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: Error
