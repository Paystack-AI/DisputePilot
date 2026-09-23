import uuid
from datetime import UTC, datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base
from app.api.models.enums import EvidenceFileType


class DisputeEvidenceFile(Base):
    __tablename__ = "dispute_evidence_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    dispute_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("disputes.id"))
    file_type: Mapped[EvidenceFileType] = mapped_column(
        PgEnum(
            EvidenceFileType,
            name="evidence_file_type",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    file_url: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(VARCHAR(255))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (PrimaryKeyConstraint("id", name="dispute_evidence_files_pk"),)
