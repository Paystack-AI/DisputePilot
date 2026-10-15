import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BOOLEAN,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class Customer(Base):
    """One customer per payer email per merchant. Ledger stats (payments, disputes,
    reconciliation coverage) are counted on read; money totals are out of scope"""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    # paystack often sends no name, so the ui falls back to the email
    name: Mapped[str | None] = mapped_column(VARCHAR(255))
    # identity, stored lowercase; null only for cash customers added by the merchant
    email: Mapped[str | None] = mapped_column(VARCHAR(255))
    phone: Mapped[str | None] = mapped_column(VARCHAR(50))
    paystack_customer_code: Mapped[str | None] = mapped_column(VARCHAR(100))
    # email used by many payers (e.g. the merchant's own); left out of per-customer evidence
    is_shared: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="customers_pk"),
        UniqueConstraint("merchant_id", "email", name="customers_merchant_email_uq"),
        UniqueConstraint(
            "merchant_id", "paystack_customer_code", name="customers_merchant_paystack_code_uq"
        ),
    )
