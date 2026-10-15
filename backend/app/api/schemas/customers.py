from datetime import datetime
from typing import Literal
from uuid import UUID

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.auth import AuthBase, LowerEmail
from app.api.schemas.pagination import PageParams

CustomerSort = Literal[
    "name",
    "-name",
    "email",
    "-email",
    "payment_count",
    "-payment_count",
    "dispute_count",
    "-dispute_count",
    "last_payment_at",
    "-last_payment_at",
    "created_at",
    "-created_at",
]


def _reject_null(value):
    if value is None:
        raise ValueError("can not be null")
    return value


class CustomerContact(AuthBase):
    name: str | None = Field(None, min_length=1, max_length=255)
    email: LowerEmail | None = None
    # international format with country code, stored as E.164 e.g. +2348031234567
    phone: str | None = Field(None, max_length=32)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value

        try:
            # no default region, so the country code is required
            number: phonenumbers.PhoneNumber = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError(
                "must be in international format with the country code, e.g. +2348031234567"
            ) from exc

        if not phonenumbers.is_valid_number(number):
            raise ValueError("is not a valid phone number")

        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


class CustomerCreate(CustomerContact):
    @model_validator(mode="after")
    def require_name_or_email(self) -> "CustomerCreate":
        # email is the identity; cash customers without one need at least a name
        if not self.name and not self.email:
            raise ValueError("name or email is required")
        return self


class CustomerUpdate(CustomerContact):
    # merchant override, e.g. a family email several people pay with
    is_shared: bool | None = None

    _validate_not_null = field_validator("is_shared", mode="before")(_reject_null)


class CustomerInDB(BaseModel):
    merchant_id: UUID
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    paystack_customer_code: str | None = None
    is_shared: bool = False
    first_seen_at: datetime | None = None


class CustomerListQuery(PageParams):
    search: str | None = Field(None, min_length=1, max_length=255)  # name or email
    is_shared: bool | None = None
    sort: CustomerSort = "-created_at"


class CustomerStats(BaseModel):
    """Counts only: revenue and other money totals are out of scope"""

    payment_count: int  # successful payments
    reconciled_count: int  # successful payments matched to an order
    reconciled_pct: int | None  # null until the first payment
    fulfilled_count: int  # successful payments whose order has a fulfillment record
    order_count: int
    dispute_count: int
    dispute_rate: float | None  # % of payments disputed, null until the first payment
    first_payment_at: datetime | None
    last_payment_at: datetime | None


class CustomerSummary(BaseModel):
    """Customer list row"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    email: str | None
    phone: str | None
    is_shared: bool
    payment_count: int
    reconciled_pct: int | None
    dispute_count: int
    last_payment_at: datetime | None
    first_seen_at: datetime | None
    created_at: datetime


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    email: str | None
    phone: str | None
    paystack_customer_code: str | None
    is_shared: bool
    first_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    stats: CustomerStats


class CustomerRef(BaseModel):
    """Customer as embedded in order responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    email: str | None
    is_shared: bool
