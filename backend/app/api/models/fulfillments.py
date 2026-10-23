import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import FulfillmentType


class Fulfillment(Base):
    __tablename__ = "fulfillments"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("orders.id", ondelete="CASCADE"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("transactions.id", ondelete="SET NULL")
    )
    type: Mapped[FulfillmentType] = mapped_column(
        PgEnum(
            FulfillmentType,
            name="fulfillment_type",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    delivery_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tracking_number: Mapped[str | None] = mapped_column(VARCHAR(255))
    recipient_name: Mapped[str | None] = mapped_column(VARCHAR(255))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    # proof photos are rows in files (fulfillment_id), so several can be attached
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Idempotency-Key of the create request: a retried create returns this record instead
    # of logging the delivery twice
    idempotency_key: Mapped[str | None] = mapped_column(VARCHAR(255))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="fulfillments_pk"),
        # NULLs are distinct, so creates without a key are unaffected
        UniqueConstraint(
            "merchant_id", "idempotency_key", name="fulfillments_merchant_idempotency_key_uq"
        ),
        Index("fulfillments_merchant_delivery_date_idx", "merchant_id", "delivery_date"),
        Index("fulfillments_order_id_idx", "order_id"),
        Index("fulfillments_transaction_id_idx", "transaction_id"),
    )
