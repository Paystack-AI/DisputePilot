import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    SMALLINT,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UniqueConstraint,
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
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    paystack_transaction_id: Mapped[int] = mapped_column(BIGINT)
    # unique per merchant: two paystack accounts can use the same reference
    paystack_reference: Mapped[str] = mapped_column(VARCHAR(100), index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("orders.id", ondelete="SET NULL")
    )
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
    # when the payment attempt started on paystack; every transaction has one, paid or not
    paystack_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # success only
    paystack_fees: Mapped[int | None] = mapped_column(BIGINT)
    customer_email: Mapped[str | None] = mapped_column(VARCHAR(255))
    customer_name: Mapped[str | None] = mapped_column(VARCHAR(255))
    # set at sync from the paystack customer (email, CUS code); the customer ledger key
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
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
    # set when reconciliation matched it (automatically or an accepted suggestion); null for
    # a merchant's manual match
    match_tier: Mapped[int | None] = mapped_column(SMALLINT)
    match_confidence: Mapped[int | None] = mapped_column(SMALLINT)
    # set while reconciliation_status is flagged: why the merchant flagged it for review
    flag_reason: Mapped[str | None] = mapped_column(VARCHAR(255))
    flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="transactions_pk"),
        # the sync upserts on this
        UniqueConstraint(
            "merchant_id", "paystack_transaction_id", name="transactions_merchant_paystack_id_uq"
        ),
        UniqueConstraint(
            "merchant_id", "paystack_reference", name="transactions_merchant_reference_uq"
        ),
        # the transaction list's date filter and default sort
        Index("transactions_merchant_created_at_idx", "merchant_id", "paystack_created_at"),
    )
