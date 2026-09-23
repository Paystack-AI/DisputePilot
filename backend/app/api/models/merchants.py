import uuid
from datetime import UTC, datetime

from sqlalchemy import UUID, VARCHAR, DateTime, PrimaryKeyConstraint, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    email: Mapped[str | None] = mapped_column(VARCHAR(255), unique=True)
    google_id: Mapped[str | None] = mapped_column(VARCHAR(255), unique=True)
    google_email: Mapped[str | None] = mapped_column(VARCHAR(255), unique=True)
    business_name: Mapped[str] = mapped_column(VARCHAR(255))
    paystack_integration_id: Mapped[str] = mapped_column(VARCHAR(100), unique=True)
    paystack_secret_key: Mapped[str] = mapped_column(Text)  # encrypted before saving
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="merchants_pk"),)
