import uuid
from datetime import UTC, datetime

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import TrustState


class TrustSnapshot(Base):
    __tablename__ = "trust_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    state: Mapped[TrustState] = mapped_column(
        PgEnum(
            TrustState,
            name="trust_state",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    internal_score: Mapped[int | None] = mapped_column(INTEGER)
    signals: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(VARCHAR(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="trust_snapshots_pk"),)
