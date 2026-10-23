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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class WebhookEvent(Base):
    """A verified paystack webhook delivery, stored before it is processed. Paystack retries
    until it gets a 200, so the same body can arrive more than once; body_hash makes a
    retry a no-op"""

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(VARCHAR(100))
    # sha256 of the raw body
    body_hash: Mapped[str] = mapped_column(VARCHAR(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # why processing failed, when it did
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("id", name="webhook_events_pk"),
        UniqueConstraint("merchant_id", "body_hash", name="webhook_events_merchant_body_uq"),
        Index(
            "webhook_events_unprocessed_idx",
            "received_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )
