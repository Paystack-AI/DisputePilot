import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    INTEGER,
    UUID,
    DateTime,
    ForeignKey,
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
from app.api.models.enums import EvidenceChange


class EvidenceRevision(Base):
    """One version of a dispute's evidence: generated, edited (with the merchant's reason)
    or submitted. A submitted revision holds the whole document as sent to paystack"""

    __tablename__ = "evidence_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    dispute_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("disputes.id", ondelete="CASCADE")
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(INTEGER)
    change: Mapped[EvidenceChange] = mapped_column(
        PgEnum(
            EvidenceChange, name="evidence_change", values_callable=lambda e: [m.value for m in e]
        )
    )
    # why the merchant changed it ("added the courier's delivery photo")
    reason: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    # [{file_id, caption}] attached at this version
    documents: Mapped[list | None] = mapped_column(JSONB)
    # the full document (facts included) for a submitted revision
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="evidence_revisions_pk"),
        UniqueConstraint("dispute_id", "version", name="evidence_revisions_dispute_version_uq"),
    )
