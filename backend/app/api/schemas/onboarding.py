from datetime import datetime

from pydantic import BaseModel

from app.api.models.enums import InitialSyncStatus, OnboardingStep


class OnboardingResponse(BaseModel):
    next_step: OnboardingStep
    completed: bool
    initial_sync_status: InitialSyncStatus
    initial_sync_total: int | None
    initial_sync_processed: int
    first_reconciliation_skipped: bool
    completed_at: datetime | None
