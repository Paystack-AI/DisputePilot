"""The dashboard: counts and states only. Money appears on individual records (a dispute,
an order, a payment), never as totals; no revenue, payout or settlement figures."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from app.api.models.enums import Currency, TrustState
from app.api.schemas.disputes import DisputeSummary
from app.api.schemas.readiness import ReadinessLabel
from app.api.schemas.transactions import TransactionResponse

# a dashboard period covers at most a year
MAX_PERIOD_DAYS: int = 366
DEFAULT_PERIOD_DAYS: int = 7
CHART_WINDOWS: tuple[int, ...] = (30, 90)


class DashboardQuery(BaseModel):
    # days in the merchant's timezone, both inclusive; omitted: the last 7 days
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "DashboardQuery":
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("send both date_from and date_to, or neither")
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be on or before date_to")
            if (self.date_to - self.date_from).days >= MAX_PERIOD_DAYS:
                raise ValueError(f"a period covers at most {MAX_PERIOD_DAYS} days")
        return self


class ChartQuery(BaseModel):
    days: int = 30

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: int) -> int:
        if value not in CHART_WINDOWS:
            raise ValueError("days must be 30 or 90")
        return value


class Period(BaseModel):
    date_from: date
    date_to: date
    # the period of the same length just before, which delta_pct compares against
    previous_from: date
    previous_to: date


class TransactionMetrics(BaseModel):
    # payment attempts started in the period, and the successful ones
    count: int
    successful: int
    # successful payments against the previous period; null when it had none
    delta_pct: float | None


class DisputeMetrics(BaseModel):
    # now, whatever the period: awaiting the merchant, and those under 4 hours
    open: int
    critical: int
    # opened and resolved in the period
    opened: int
    resolved: int


class ReadinessMetrics(BaseModel):
    """Matched payments of the period"""

    score: int | None
    label: ReadinessLabel | None
    # percent of the period's matched payments in each band
    distribution: dict[ReadinessLabel, int]


class ReconciliationMetrics(BaseModel):
    # successful payments of the period matched to an order
    matched_pct: float | None
    # now: successful payments with no order and no flag
    unmatched: int
    # matched_pct against the previous period, in points; null when either had none
    delta_pct: float | None


class DashboardMetrics(BaseModel):
    transactions: TransactionMetrics | None
    disputes: DisputeMetrics | None
    readiness: ReadinessMetrics | None
    reconciliation: ReconciliationMetrics | None


class CriticalDispute(BaseModel):
    id: UUID
    paystack_dispute_id: str
    amount: int
    currency: Currency
    due_at: datetime
    customer_name: str | None


class ReconciliationBlock(BaseModel):
    synced_today: int
    matched_today: int
    needs_review: int
    last_completed_at: datetime | None


class TrustBlock(BaseModel):
    state: TrustState
    label: str
    updated_at: datetime | None


class FulfillmentPrompt(BaseModel):
    type: Literal["log_fulfillment"] = "log_fulfillment"
    order_id: UUID
    order_number: str | None
    amount: int
    currency: Currency


ActivityType = Literal[
    "dispute_created",
    "dispute_submitted",
    "dispute_won",
    "dispute_lost",
    "dispute_auto_accepted",
    "fulfillment_logged",
    "reconciliation_completed",
    "trust_changed",
]


class ActivityLink(BaseModel):
    type: Literal["dispute", "order", "reconciliation_session", "trust"]
    id: UUID | None


class ActivityItem(BaseModel):
    type: ActivityType
    occurred_at: datetime
    title: str
    link: ActivityLink


class Dashboard(BaseModel):
    """Every block is nullable on its own: one failing never blanks the page"""

    server_time: datetime
    currency: Currency
    period: Period
    metrics: DashboardMetrics
    # the soonest dispute under 8 hours; null when none is that close
    critical_dispute: CriticalDispute | None
    reconciliation: ReconciliationBlock | None
    trust: TrustBlock | None
    # paid orders with no fulfillment yet, newest first
    prompts: list[FulfillmentPrompt] | None
    recent_transactions: list[TransactionResponse] | None
    recent_disputes: list[DisputeSummary] | None
    activity: list[ActivityItem] | None


class DisputeTimelineDay(BaseModel):
    date: date
    opened: int
    won: int
    lost: int
    auto_accepted: int


class DisputeTimeline(BaseModel):
    days: int
    series: list[DisputeTimelineDay]


class MatchRateDay(BaseModel):
    date: date
    payments: int
    matched: int
    matched_pct: float | None


class ReconciliationHealth(BaseModel):
    days: int
    sessions_started: int
    sessions_completed: int
    # completed out of started
    completion_rate: float | None
    # unmatched payments, unmatched orders and flagged, per completed session
    avg_mismatches: float | None
    series: list[MatchRateDay]
