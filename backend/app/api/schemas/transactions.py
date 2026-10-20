from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.models.enums import (
    Currency,
    DisputeStatus,
    OrderSource,
    OrderStatus,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
)
from app.api.schemas.auth import AuthBase
from app.api.schemas.customers import CustomerRef
from app.api.schemas.fulfillments import FulfillmentSummary
from app.api.schemas.pagination import PageParams
from app.api.schemas.readiness import Readiness, ReadinessDetail

TransactionSort = Literal["created_at", "-created_at", "paid_at", "-paid_at", "amount", "-amount"]


def _split_comma_list(value):
    """?status=success,failed and repeated params both give a list"""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return [item.strip() for item in value[0].split(",") if item.strip()]
    return value


class TransactionSummary(BaseModel):
    """Synced paystack payment as embedded in customer and order responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str = Field(validation_alias="paystack_reference")
    paystack_transaction_id: str
    amount: int
    currency: Currency
    channel: TransactionChannel
    status: TransactionStatus
    paid_at: datetime | None
    customer_email: str | None
    order_id: UUID | None
    reconciliation_status: ReconciliationStatus
    reconciled_at: datetime | None

    @field_validator("paystack_transaction_id", mode="before")
    @classmethod
    def stringify_paystack_id(cls, value: int | str) -> str:
        return str(value)


class TransactionListQuery(PageParams):
    # comma lists, e.g. ?status=success,reversed
    status: list[TransactionStatus] | None = None
    reconciliation_status: list[ReconciliationStatus] | None = None
    customer_id: UUID | None = None
    # YYYY-MM-DD in the merchant's timezone, both inclusive, on when the attempt started
    # (paid or not); ?status=success narrows it to paid
    date_from: date | None = None
    date_to: date | None = None
    sort: TransactionSort = "-created_at"

    _split_lists = field_validator("status", "reconciliation_status", mode="before")(
        _split_comma_list
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "TransactionListQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class TransactionOrderRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str | None


class TransactionResponse(TransactionSummary):
    """Synced paystack payment with its customer and linked order"""

    customer: CustomerRef | None
    order: TransactionOrderRef | None
    paystack_fees: int | None
    customer_name: str | None
    created_at: datetime  # when the attempt started on paystack
    flag_reason: str | None
    flagged_at: datetime | None
    synced_at: datetime
    # dispute readiness; null unless the payment is matched to an order
    readiness: Readiness | None = None


class TransactionOrder(TransactionOrderRef):
    description: str | None
    amount: int
    currency: Currency
    status: OrderStatus
    source: OrderSource
    created_at: datetime


class TransactionDispute(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    paystack_dispute_id: str
    status: DisputeStatus
    amount: int
    currency: Currency
    due_at: datetime
    created_at: datetime

    @field_validator("paystack_dispute_id", mode="before")
    @classmethod
    def stringify_paystack_id(cls, value: int | str) -> str:
        return str(value)


class TransactionDetail(TransactionResponse):
    """One payment with everything linked to it"""

    order: TransactionOrder | None
    metadata: dict | None
    fulfillments: list[FulfillmentSummary]
    dispute: TransactionDispute | None
    # with the checklist of what counts towards it
    readiness: ReadinessDetail | None = None


class TransactionMatch(AuthBase):
    order_id: UUID


class TransactionFlag(AuthBase):
    reason: str = Field(..., min_length=1, max_length=255)


class TransactionSyncResponse(BaseModel):
    status: Literal["queued"] = "queued"
    # where the sync starts; null means the last 30 days (never synced before)
    last_sync_at: datetime | None
