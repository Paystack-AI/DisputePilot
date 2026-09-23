import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
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
from app.api.models.enums import (
    NotificationChannel,
    NotificationMessageType,
    NotificationStatus,
)


class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"))
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("disputes.id"))
    channel: Mapped[NotificationChannel] = mapped_column(
        PgEnum(
            NotificationChannel,
            name="notification_channel",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    message_type: Mapped[NotificationMessageType] = mapped_column(
        PgEnum(
            NotificationMessageType,
            name="notification_message_type",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    status: Mapped[NotificationStatus] = mapped_column(
        PgEnum(
            NotificationStatus,
            name="notification_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=NotificationStatus.PENDING,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    __table_args__ = (PrimaryKeyConstraint("id", name="notifications_log_pk"),)
