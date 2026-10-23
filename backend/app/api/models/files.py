import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BIGINT,
    INTEGER,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.api.models.base import Base


class StoredFile(Base):
    """An uploaded image in object storage, shared by fulfillments and (later) disputes.
    A file with neither link is unattached; unattached files are deleted after a day"""

    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id", ondelete="CASCADE")
    )
    fulfillment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("fulfillments.id", ondelete="SET NULL")
    )
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("disputes.id", ondelete="SET NULL")
    )
    # key in the bucket; internal only, never returned to clients
    object_name: Mapped[str] = mapped_column(Text)
    # the name the merchant uploaded, for display
    file_name: Mapped[str] = mapped_column(VARCHAR(255))
    content_type: Mapped[str] = mapped_column(VARCHAR(100))
    # the merchant's label for a dispute document, shown in the evidence pdf
    caption: Mapped[str | None] = mapped_column(VARCHAR(255))
    size: Mapped[int] = mapped_column(BIGINT)  # bytes, as stored
    width: Mapped[int] = mapped_column(INTEGER)
    height: Mapped[int] = mapped_column(INTEGER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="files_pk"),
        UniqueConstraint("object_name", name="files_object_name_uq"),
        Index("files_merchant_id_idx", "merchant_id"),
        Index("files_fulfillment_id_idx", "fulfillment_id"),
        Index("files_dispute_id_idx", "dispute_id"),
        # the cleanup task's lookup of old unattached files
        Index(
            "files_unattached_created_at_idx",
            "created_at",
            postgresql_where=text("fulfillment_id IS NULL AND dispute_id IS NULL"),
        ),
    )
