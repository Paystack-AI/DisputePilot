from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.api.models.enums import ReconciliationSessionStatus
from app.api.schemas.auth import AuthBase
from app.api.schemas.orders import OrderResponse
from app.api.schemas.transactions import TransactionResponse

# a session covers at most a month of payments
MAX_SESSION_DAYS: int = 31


class ReconciliationStart(AuthBase):
    # days in the merchant's timezone, both inclusive; omitted: the merchant's default
    # reconciliation range ending today
    date_range_start: date | None = None
    date_range_end: date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "ReconciliationStart":
        if (self.date_range_start is None) != (self.date_range_end is None):
            raise ValueError("send both date_range_start and date_range_end, or neither")
        if self.date_range_start and self.date_range_end:
            if self.date_range_start > self.date_range_end:
                raise ValueError("date_range_start must be on or before date_range_end")
            if (self.date_range_end - self.date_range_start).days >= MAX_SESSION_DAYS:
                raise ValueError(f"a session covers at most {MAX_SESSION_DAYS} days")
        return self


class MatchDecision(AuthBase):
    transaction_id: UUID
    order_id: UUID


class ReconciliationTotals(BaseModel):
    # successful payments paid in the range; each is in exactly one of the four below
    total_transactions: int
    matched: int
    suggested: int
    unmatched_payments: int
    flagged: int
    # pending orders created in the range that nothing matched or suggested
    unmatched_orders: int


class ReconciliationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    date_range_start: date
    date_range_end: date
    status: ReconciliationSessionStatus
    # live while in progress; the counts saved at completion afterwards
    totals: ReconciliationTotals
    completed_at: datetime | None
    created_at: datetime


class MatchedItem(BaseModel):
    transaction: TransactionResponse
    order: OrderResponse
    # set when reconciliation found the match; null for a match made by hand
    tier: int | None
    confidence: int | None
    accepted_at: datetime | None


class SuggestionItem(BaseModel):
    id: UUID
    transaction: TransactionResponse
    order: OrderResponse
    tier: int
    likelihood_percent: int
    confidence_tier: Literal["likely", "possible"]
    reasoning: str


class FlaggedPayment(BaseModel):
    transaction: TransactionResponse
    reason: str | None


class FlaggedOrder(BaseModel):
    order: OrderResponse
    reason: str | None


class ReconciliationView(BaseModel):
    """A session and its payments by category. Each list holds at most LIST_LIMIT items,
    newest first; totals has the full counts"""

    session: ReconciliationSessionResponse
    matched: list[MatchedItem]
    suggestions: list[SuggestionItem]
    unmatched_payments: list[TransactionResponse]
    unmatched_orders: list[OrderResponse]
    flagged: list[FlaggedPayment]
    flagged_orders: list[FlaggedOrder]


class MatchDecisionResponse(BaseModel):
    transaction: TransactionResponse
    # the open session's live totals; null when no session is open
    totals: ReconciliationTotals | None


class ReconciliationSummary(BaseModel):
    # payments synced since the start of today, in the merchant's timezone
    synced_today: int
    # payments linked to an order since the start of today
    matched_today: int
    # successful payments of the last 30 days that are unmatched, suggested or flagged
    needs_review: int
    last_completed_at: datetime | None
