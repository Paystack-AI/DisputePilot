import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import (
    Currency,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    paystack_transaction_id: Mapped[int] = mapped_column(BIGINT)
    paystack_reference: Mapped[str] = mapped_column(VARCHAR(100), unique=True, index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("orders.id"))
    amount: Mapped[int] = mapped_column(BIGINT)
    currency: Mapped[Currency] = mapped_column(
        PgEnum(
            Currency,
            name="currency_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=Currency.NGN,
    )
    channel: Mapped[TransactionChannel] = mapped_column(
        PgEnum(
            TransactionChannel,
            name="transaction_channel",
            values_callable=lambda e: [m.value for m in e],
        ),
    )
    status: Mapped[TransactionStatus] = mapped_column(
        PgEnum(
            TransactionStatus,
            name="transaction_status",
            values_callable=lambda e: [m.value for m in e],
        ),
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paystack_fees: Mapped[int | None] = mapped_column(BIGINT)
    customer_email: Mapped[str | None] = mapped_column(VARCHAR(255))
    customer_name: Mapped[str | None] = mapped_column(VARCHAR(255))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        PgEnum(
            ReconciliationStatus,
            name="reconciliation_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ReconciliationStatus.UNMATCHED,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="transactions_pk"),)
