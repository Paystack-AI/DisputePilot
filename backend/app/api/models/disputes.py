import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    FLOAT,
    INTEGER,
    UUID,
    VARCHAR,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    Text,
    text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import (
    Currency,
    DisputeCategory,
    DisputeStatus,
    SubmissionFlow,
)


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("transactions.id"))
    paystack_dispute_id: Mapped[int] = mapped_column(BIGINT)
    paystack_reference: Mapped[str] = mapped_column(VARCHAR(100))
    amount: Mapped[int] = mapped_column(BIGINT)
    currency: Mapped[Currency] = mapped_column(
        PgEnum(
            Currency,
            name="currency_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=Currency.NGN,
    )
    category: Mapped[DisputeCategory | None] = mapped_column(
        PgEnum(
            DisputeCategory,
            name="dispute_category",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    category_confidence: Mapped[float | None] = mapped_column(FLOAT)
    paystack_category: Mapped[str | None] = mapped_column(VARCHAR(50))
    reason_raw: Mapped[str | None] = mapped_column(Text)
    submission_flow: Mapped[SubmissionFlow | None] = mapped_column(
        PgEnum(
            SubmissionFlow,
            name="submission_flow",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    paystack_evidence_id: Mapped[int | None] = mapped_column(INTEGER)
    status: Mapped[DisputeStatus] = mapped_column(
        PgEnum(
            DisputeStatus,
            name="dispute_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DisputeStatus.PENDING,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_narrative: Mapped[str | None] = mapped_column(Text)
    evidence_pdf_url: Mapped[str | None] = mapped_column(Text)
    evidence_quality_score: Mapped[float | None] = mapped_column(FLOAT)
    evidence_suggestions: Mapped[dict | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(VARCHAR(20))
    paystack_resolution: Mapped[str | None] = mapped_column(VARCHAR(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="disputes_pk"),)
