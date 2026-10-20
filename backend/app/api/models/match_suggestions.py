import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    SMALLINT,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import MatchSuggestionStatus


class MatchSuggestion(Base):
    """A likely payment -> order match reconciliation found but did not link on its own
    (tier 2 with several candidates, tier 3, or tier 1 with auto-confirm off). Rejected
    pairs stay so they are never suggested or auto-matched again"""

    __tablename__ = "match_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("transactions.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("orders.id", ondelete="CASCADE"))
    tier: Mapped[int] = mapped_column(SMALLINT)
    confidence: Mapped[int] = mapped_column(SMALLINT)  # percent
    reason: Mapped[str] = mapped_column(VARCHAR(255))
    status: Mapped[MatchSuggestionStatus] = mapped_column(
        PgEnum(
            MatchSuggestionStatus,
            name="match_suggestion_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=MatchSuggestionStatus.PENDING,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="match_suggestions_pk"),
        UniqueConstraint("transaction_id", "order_id", name="match_suggestions_pair_uq"),
        Index("match_suggestions_merchant_status_idx", "merchant_id", "status"),
        Index("match_suggestions_order_idx", "order_id"),
    )
