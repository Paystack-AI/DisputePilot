from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.models.enums import (
    Currency,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
)


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
