from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, SerializeAsAny

from app.api.schemas.pagination import PageMeta

T = TypeVar("T", bound=BaseModel)


class SuccessResponse(BaseModel, Generic[T]):
    data: T


class ListSuccessResponse(BaseModel, Generic[T]):
    data: list[T]
    # a subclass's extra fields (e.g. server_time) are kept
    meta: SerializeAsAny[PageMeta]


class Error(BaseModel):
    code: str
    message: str
    request_id: UUID
    details: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: Error
