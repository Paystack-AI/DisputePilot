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
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class MerchantSettings(Base):
    __tablename__ = "merchant_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"), unique=True)
    notification_whatsapp: Mapped[str | None] = mapped_column(VARCHAR(50))
    notification_email: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    auto_reconciliation_tier1: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    default_reconciliation_range: Mapped[int] = mapped_column(INTEGER, default=1)
    trust_public_enabled: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    trust_widget_enabled: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="merchant_settings_pk"),)
