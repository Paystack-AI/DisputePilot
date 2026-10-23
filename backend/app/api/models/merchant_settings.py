import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BOOLEAN,
    INTEGER,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import Currency


class MerchantSettings(Base):
    __tablename__ = "merchant_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE"), unique=True
    )
    notification_email: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    auto_reconciliation_tier1: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    default_reconciliation_range: Mapped[int] = mapped_column(INTEGER, default=1)
    trust_public_enabled: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    trust_widget_enabled: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    # IANA name, used only for display and date-range bucketing; storage stays UTC
    timezone: Mapped[str] = mapped_column(VARCHAR(64), default="UTC")
    default_currency: Mapped[Currency] = mapped_column(
        PgEnum(
            Currency,
            name="currency_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=Currency.NGN,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="merchant_settings_pk"),)
