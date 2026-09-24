from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class SuccessResponse(BaseModel, Generic[T]):
    data: T


class ListSuccessResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: dict  # contains additional metadata such as cursor and limit for pagination


class Error(BaseModel):
    code: str
    message: str
    request_id: UUID
    details: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: Error
