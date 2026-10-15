from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.models.enums import Currency, OrderSource, OrderStatus
from app.api.schemas.auth import AuthBase, LowerEmail
from app.api.schemas.customers import CustomerRef
from app.api.schemas.fulfillments import FulfillmentSummary
from app.api.schemas.pagination import PageParams
from app.api.schemas.transactions import TransactionSummary

OrderSort = Literal[
    "created_at",
    "-created_at",
    "amount",
    "-amount",
    "order_number",
    "-order_number",
]

# optional and merchant-entered; the same value in paystack metadata or the reference
# auto-matches the payment (tier 1)
OrderNumber = Field(None, min_length=1, max_length=50)


def _reject_null(value):
    if value is None:
        raise ValueError("can not be null")
    return value


class OrderCreate(AuthBase):
    order_number: str | None = OrderNumber
    # an existing customer, or an email that is linked to (or creates) the customer;
    # a customer email lets reconciliation match the payment by email (tier 2)
    customer_id: UUID | None = None
    customer_email: LowerEmail | None = None
    description: str | None = Field(None, max_length=2000)
    amount: int = Field(..., gt=0)  # smallest currency unit, e.g. kobo
    currency: Currency | None = None  # defaults to the merchant's default currency
    source: OrderSource = OrderSource.OTHER

    @model_validator(mode="after")
    def validate_customer(self) -> "OrderCreate":
        if self.customer_id and self.customer_email:
            raise ValueError("send customer_id or customer_email, not both")
        return self


class OrderUpdate(AuthBase):
    # null clears the order number or detaches the customer
    order_number: str | None = OrderNumber
    customer_id: UUID | None = None
    description: str | None = Field(None, max_length=2000)
    amount: int | None = Field(None, gt=0)
    currency: Currency | None = None
    source: OrderSource | None = None
    status: OrderStatus | None = None

    _validate_not_null = field_validator("amount", "currency", "source", "status", mode="before")(
        _reject_null
    )


class OrderInDB(BaseModel):
    merchant_id: UUID
    customer_id: UUID | None = None
    order_number: str | None = None
    description: str | None = None
    amount: int
    currency: Currency
    source: OrderSource


class OrderListQuery(PageParams):
    # comma list, e.g. ?status=pending,paid
    status: list[OrderStatus] | None = None
    customer_id: UUID | None = None
    # YYYY-MM-DD in the merchant's timezone, both inclusive
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = Field(None, min_length=1, max_length=255)  # number, description, customer
    sort: OrderSort = "-created_at"

    @field_validator("status", mode="before")
    @classmethod
    def split_status(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            return [item.strip() for item in value[0].split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "OrderListQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str | None
    customer: CustomerRef | None
    description: str | None
    amount: int
    currency: Currency
    status: OrderStatus
    source: OrderSource
    # linked to a synced payment; order_number, amount, currency and customer are then locked
    is_linked: bool
    created_at: datetime
    updated_at: datetime | None


class OrderDetail(OrderResponse):
    transactions: list[TransactionSummary]
    fulfillments: list[FulfillmentSummary]
