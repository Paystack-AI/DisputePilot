import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    FLOAT,
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
from app.api.models.enums import TrustState


class TrustProfile(Base):
    __tablename__ = "trust_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"), unique=True)
    current_state: Mapped[TrustState] = mapped_column(
        PgEnum(
            TrustState,
            name="trust_state",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=TrustState.NEW,
    )
    internal_score: Mapped[int | None] = mapped_column(INTEGER)
    reconciliation_rate: Mapped[float | None] = mapped_column(FLOAT)
    fulfillment_rate: Mapped[float | None] = mapped_column(FLOAT)
    dispute_rate: Mapped[float | None] = mapped_column(FLOAT)
    dispute_win_rate: Mapped[float | None] = mapped_column(FLOAT)
    avg_response_time_pct: Mapped[float | None] = mapped_column(FLOAT)
    evidence_readiness_avg: Mapped[float | None] = mapped_column(FLOAT)
    public_token: Mapped[str] = mapped_column(VARCHAR(64), unique=True)
    last_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="trust_profiles_pk"),)
