import uuid
from datetime import UTC, datetime

from sqlalchemy import BOOLEAN, UUID, VARCHAR, DateTime, PrimaryKeyConstraint, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class Admin(Base):
    """A separate operator account: it can read every merchant, but owns no data."""

    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    email: Mapped[str] = mapped_column(VARCHAR(255), unique=True)
    name: Mapped[str | None] = mapped_column(VARCHAR(255))
    hashed_password: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(BOOLEAN, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="admins_pk"),)
