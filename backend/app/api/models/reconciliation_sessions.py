import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    DATE,
    INTEGER,
    UUID,
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
from app.api.models.enums import ReconciliationSessionStatus


class ReconciliationSession(Base):
    __tablename__ = "reconciliation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    date_range_start: Mapped[date] = mapped_column(DATE)
    date_range_end: Mapped[date] = mapped_column(DATE)
    total_transactions: Mapped[int] = mapped_column(INTEGER, default=0)
    matched_count: Mapped[int] = mapped_column(INTEGER, default=0)
    unmatched_payments_count: Mapped[int] = mapped_column(INTEGER, default=0)
    unmatched_orders_count: Mapped[int] = mapped_column(INTEGER, default=0)
    flagged_count: Mapped[int] = mapped_column(INTEGER, default=0)
    status: Mapped[ReconciliationSessionStatus] = mapped_column(
        PgEnum(
            ReconciliationSessionStatus,
            name="reconciliation_session_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ReconciliationSessionStatus.IN_PROGRESS,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="reconciliation_sessions_pk"),)
