import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BOOLEAN,
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
from app.api.models.enums import InitialSyncStatus, OnboardingStep


class MerchantOnboarding(Base):
    __tablename__ = "merchant_onboarding"

    id: Mapped[uuid.UUID] = mapped_column(UUID, server_default=text("uuid_generate_v7()"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("merchants.id"), unique=True)
    current_step: Mapped[OnboardingStep] = mapped_column(
        PgEnum(
            OnboardingStep,
            name="onboarding_step",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=OnboardingStep.CONNECT_PAYSTACK,
    )
    # step 3: pull the last 30 days of transactions; counts drive the progress bar
    initial_sync_status: Mapped[InitialSyncStatus] = mapped_column(
        PgEnum(
            InitialSyncStatus,
            name="initial_sync_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=InitialSyncStatus.NOT_STARTED,
    )
    initial_sync_total: Mapped[int | None] = mapped_column(INTEGER)
    initial_sync_processed: Mapped[int] = mapped_column(INTEGER, default=0)
    # step 4 can be deferred ("do it later"), which still completes onboarding
    first_reconciliation_skipped: Mapped[bool] = mapped_column(BOOLEAN, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (PrimaryKeyConstraint("id", name="merchant_onboarding_pk"),)
