import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    Text,
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
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("orders.id"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("transactions.id"))
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
    proof_photo_url: Mapped[str | None] = mapped_column(Text)
    proof_document_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="fulfillments_pk"),)
