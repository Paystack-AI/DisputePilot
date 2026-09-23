import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    INTEGER,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    name: Mapped[str] = mapped_column(VARCHAR(255))
    email: Mapped[str | None] = mapped_column(VARCHAR(255))
    phone: Mapped[str | None] = mapped_column(VARCHAR(50))
    paystack_customer_code: Mapped[str | None] = mapped_column(VARCHAR(100))
    total_transactions: Mapped[int] = mapped_column(INTEGER, default=0)
    total_spent: Mapped[int] = mapped_column(BIGINT, default=0)
    total_outstanding: Mapped[int] = mapped_column(BIGINT, default=0)
    total_disputes: Mapped[int] = mapped_column(INTEGER, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="customers_pk"),)
