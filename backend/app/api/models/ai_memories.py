import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    UUID,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    VARCHAR,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class AiMemory(Base):
    """Durable, tenant-scoped retrieval records for AI context.

    The source record remains authoritative. Memory is an indexed summary/context layer and
    must never be treated as verified facts merely because it is stored.
    """

    __tablename__ = "ai_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("disputes.id"))
    memory_type: Mapped[str] = mapped_column(VARCHAR(50))
    source_type: Mapped[str] = mapped_column(VARCHAR(50))
    source_id: Mapped[str] = mapped_column(VARCHAR(100))
    content: Mapped[dict] = mapped_column(JSONB)
    content_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(VARCHAR(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    corrected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("ai_memories.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("id", name="ai_memories_pk"),
        CheckConstraint("tenant_id = merchant_id", name="ai_memories_tenant_merchant_ck"),
        UniqueConstraint(
            "tenant_id", "merchant_id", "source_type", "source_id", name="ai_memories_source_uq"
        ),
        Index(
            "ai_memories_tenant_scope_idx",
            "tenant_id",
            "merchant_id",
            "dispute_id",
            "occurred_at",
        ),
        Index("ai_memories_source_idx", "tenant_id", "merchant_id", "source_type", "source_id"),
    )


class AiMemoryAccessAudit(Base):
    """Access metadata only; never stores memory content."""

    __tablename__ = "ai_memory_access_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    action: Mapped[str] = mapped_column(VARCHAR(20))
    memory_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    memory_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="ai_memory_access_audit_pk"),
        CheckConstraint(
            "tenant_id = merchant_id", name="ai_memory_audit_tenant_merchant_ck"
        ),
        Index("ai_memory_audit_scope_idx", "tenant_id", "merchant_id", "created_at"),
    )
