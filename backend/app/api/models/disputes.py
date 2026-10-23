import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    FLOAT,
    INTEGER,
    SMALLINT,
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
    EvidenceState,
    EvidenceStep,
    GenerationSource,
    SubmissionFlow,
    SubmissionState,
)


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("transactions.id", ondelete="CASCADE")
    )
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
    # paystack's own status, e.g. awaiting-merchant-feedback, awaiting-bank-feedback, resolved
    paystack_status: Mapped[str | None] = mapped_column(VARCHAR(50))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # last time a webhook or the poller updated it from paystack
    paystack_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ---- evidence: the ai chain (classify -> generate -> score) and its draft ----
    evidence_state: Mapped[EvidenceState | None] = mapped_column(
        PgEnum(EvidenceState, name="evidence_state", values_callable=lambda e: [m.value for m in e])
    )
    evidence_step: Mapped[EvidenceStep | None] = mapped_column(
        PgEnum(EvidenceStep, name="evidence_step", values_callable=lambda e: [m.value for m in e])
    )
    # the running chain's job id; results for an older job (a regenerate) are ignored
    ai_job_id: Mapped[str | None] = mapped_column(VARCHAR(64))
    # when the current step was sent to the ai; a step quiet for too long falls back
    evidence_step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_source: Mapped[GenerationSource | None] = mapped_column(
        PgEnum(
            GenerationSource,
            name="generation_source",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # from the classifier
    evidence_strategy: Mapped[list | None] = mapped_column(JSONB)
    special_instructions: Mapped[str | None] = mapped_column(Text)
    # the editable parts of the draft; facts (receipt, order, fulfillment, customer history)
    # are read from the database whenever the document is built
    evidence_conclusion: Mapped[str | None] = mapped_column(Text)
    missing_evidence: Mapped[list | None] = mapped_column(JSONB)
    evidence_items_referenced: Mapped[list | None] = mapped_column(JSONB)
    # dimension scores and ready_to_submit from the scorer
    evidence_quality: Mapped[dict | None] = mapped_column(JSONB)
    # bumped on every change to the draft; edits and submit send the version they saw
    evidence_version: Mapped[int] = mapped_column(INTEGER, default=0, server_default="0")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ---- submission ----
    submission_state: Mapped[SubmissionState | None] = mapped_column(
        PgEnum(
            SubmissionState,
            name="submission_state",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    submission_error: Mapped[str | None] = mapped_column(Text)
    # bucket key of the generated pdf (internal; downloaded through the api)
    evidence_pdf_object: Mapped[str | None] = mapped_column(Text)
    # paystack's name for the uploaded pdf, passed to resolve
    paystack_uploaded_filename: Mapped[str | None] = mapped_column(VARCHAR(255))
    # the deadline warning last sent (8 or 4 hours left), so each goes out once
    last_deadline_warning_hours: Mapped[int | None] = mapped_column(SMALLINT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="disputes_pk"),
        # webhooks and the poller upsert on this
        UniqueConstraint(
            "merchant_id", "paystack_dispute_id", name="disputes_merchant_paystack_id_uq"
        ),
        Index("disputes_due_at_idx", "due_at"),
        Index(
            "disputes_generating_idx",
            "evidence_step_started_at",
            postgresql_where=text("evidence_state = 'generating'"),
        ),
    )
