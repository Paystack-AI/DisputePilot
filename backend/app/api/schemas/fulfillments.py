from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.models.enums import FulfillmentType
from app.api.schemas.auth import AuthBase
from app.api.schemas.files import FileResponse
from app.api.schemas.pagination import PageParams
from app.core.config import get_settings

SETTINGS = get_settings()

FulfillmentSort = Literal["delivery_date", "-delivery_date", "created_at", "-created_at"]
# ids from POST /uploads; a fulfillment holds at most this many photos
FileIds = Field(None, max_length=SETTINGS.UPLOAD_MAX_FILES)


def _reject_null(value):
    if value is None:
        raise ValueError("can not be null")
    return value


def _unique(value: list[UUID] | None) -> list[UUID] | None:
    if value is not None and len(set(value)) != len(value):
        raise ValueError("file ids must be unique")
    return value


class FulfillmentCreate(AuthBase):
    order_id: UUID
    # the payment this proves; defaults to the order's linked payment
    transaction_id: UUID | None = None
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None = Field(None, max_length=255)
    recipient_name: str | None = Field(None, max_length=255)
    delivery_address: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=2000)
    file_ids: list[UUID] | None = FileIds

    _validate_files = field_validator("file_ids")(_unique)


class FulfillmentUpdate(AuthBase):
    """Omitted fields are unchanged; file_ids replaces the attached photos"""

    type: FulfillmentType | None = None
    delivery_date: datetime | None = None
    tracking_number: str | None = Field(None, max_length=255)
    recipient_name: str | None = Field(None, max_length=255)
    delivery_address: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=2000)
    file_ids: list[UUID] | None = FileIds

    _validate_not_null = field_validator("type", "delivery_date", "file_ids", mode="before")(
        _reject_null
    )
    _validate_files = field_validator("file_ids")(_unique)


class FulfillmentInDB(BaseModel):
    merchant_id: UUID
    order_id: UUID
    transaction_id: UUID | None = None
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None = None
    recipient_name: str | None = None
    delivery_address: str | None = None
    notes: str | None = None
    idempotency_key: str | None = None


class FulfillmentListQuery(PageParams):
    order_id: UUID | None = None
    transaction_id: UUID | None = None
    sort: FulfillmentSort = "-delivery_date"


class FulfillmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    transaction_id: UUID | None
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None
    recipient_name: str | None
    delivery_address: str | None
    notes: str | None
    files: list[FileResponse]  # proof photos, oldest first
    created_at: datetime
    updated_at: datetime | None


class FulfillmentSummary(BaseModel):
    """Fulfillment record as embedded in order responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID | None
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None
    recipient_name: str | None
    created_at: datetime
