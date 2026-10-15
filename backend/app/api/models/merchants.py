import uuid
from datetime import UTC, datetime

from sqlalchemy import UUID, VARCHAR, DateTime, PrimaryKeyConstraint, Text, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import PaystackMode


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    email: Mapped[str] = mapped_column(VARCHAR(255), unique=True)
    google_id: Mapped[str | None] = mapped_column(VARCHAR(255), unique=True)
    business_name: Mapped[str] = mapped_column(VARCHAR(255))
    paystack_integration_id: Mapped[str] = mapped_column(VARCHAR(100), unique=True)
    paystack_secret_key: Mapped[str | None] = mapped_column(Text)  # encrypted before saving
    # live|test, known once the secret key has been validated against Paystack
    paystack_mode: Mapped[PaystackMode | None] = mapped_column(
        PgEnum(
            PaystackMode,
            name="paystack_mode",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # last time the secret key was (re)connected; keys can be rotated on the Paystack dashboard
    paystack_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="merchants_pk"),)
