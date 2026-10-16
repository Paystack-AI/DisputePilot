import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    Index,
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
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("customers.id"), index=True
    )
    # optional, entered by the merchant; matched against paystack metadata or the reference
    # (tier 1), so unique per merchant ignoring case
    order_number: Mapped[str | None] = mapped_column(VARCHAR(50))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(BIGINT)  # smallest currency unit, e.g. kobo
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

    __table_args__ = (
        PrimaryKeyConstraint("id", name="orders_pk"),
        Index(
            "orders_merchant_order_number_uq",
            "merchant_id",
            text("lower(order_number)"),
            unique=True,
            postgresql_where=text("order_number IS NOT NULL"),
        ),
        # trigram indexes serve the search's ILIKE '%term%' (pg_trgm)
        Index(
            "orders_order_number_trgm_idx",
            "order_number",
            postgresql_using="gin",
            postgresql_ops={"order_number": "gin_trgm_ops"},
        ),
        Index(
            "orders_description_trgm_idx",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )
