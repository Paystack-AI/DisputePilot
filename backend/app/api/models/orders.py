import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import Currency, OrderSource, OrderStatus


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("customers.id"))
    order_number: Mapped[str] = mapped_column(VARCHAR(50))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(BIGINT)
    currency: Mapped[Currency] = mapped_column(
        PgEnum(
            Currency,
            name="currency_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=Currency.NGN,
    )
    status: Mapped[OrderStatus] = mapped_column(
        PgEnum(
            OrderStatus,
            name="order_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=OrderStatus.PENDING,
    )
    source: Mapped[OrderSource] = mapped_column(
        PgEnum(
            OrderSource,
            name="order_source",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="orders_pk"),)
