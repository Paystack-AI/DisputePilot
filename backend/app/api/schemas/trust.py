from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.api.models.enums import TrustState
from app.api.schemas.auth import AuthBase

Reading = Literal["strong", "fair", "weak", "insufficient"]
SignalKey = Literal[
    "reconciliation_rate",
    "fulfillment_rate",
    "dispute_rate",
    "dispute_win_rate",
    "avg_response_time",
    "evidence_readiness",
]


class TrustSignal(BaseModel):
    key: SignalKey
    label: str
    # percent (0-100); null when there is nothing to measure yet
    value: float | None
    # strong: meets the verified threshold; fair: building; weak: below
    reading: Reading
    # e.g. "at least 80%"; null for signals no state depends on
    verified_threshold: str | None
    building_threshold: str | None
    # what would move it up; null when it is already strong
    action: str | None


class TrustSample(BaseModel):
    payments_30d: int
    days_on_platform: int
    # below it the state is new whatever the signals
    min_sample_met: bool


class TrustProfileResponse(BaseModel):
    """The merchant's own view: everything, including the internal score"""

    state: TrustState
    label: str
    meaning: str
    internal_score: int | None
    signals: list[TrustSignal]
    sample: TrustSample | None
    public_enabled: bool
    widget_enabled: bool
    public_url: str
    last_computed_at: datetime | None
    # when the current state began
    stable_since: datetime | None


class TrustSettingsUpdate(AuthBase):
    public_enabled: bool | None = None
    widget_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_change(self) -> "TrustSettingsUpdate":
        if self.public_enabled is None and self.widget_enabled is None:
            raise ValueError("send public_enabled or widget_enabled")
        return self


class TrustSignalsBreakdown(BaseModel):
    state: TrustState
    # the next state up and the signals keeping the merchant from it
    next_state: TrustState | None
    blocking: list[SignalKey]
    contributing: list[SignalKey]
    signals: list[TrustSignal]
    sample: TrustSample | None


HISTORY_WINDOWS: tuple[int, ...] = (7, 30, 90)


class TrustHistoryQuery(BaseModel):
    days: int = 30

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: int) -> int:
        if value not in HISTORY_WINDOWS:
            raise ValueError("days must be 7, 30 or 90")
        return value


class TrustHistoryPoint(BaseModel):
    at: datetime
    state: TrustState
    internal_score: int | None
    reason: str
    signals: dict


class TrustStateChange(BaseModel):
    at: datetime
    from_state: TrustState | None
    to_state: TrustState
    reason: str


class TrustHistory(BaseModel):
    days: int
    points: list[TrustHistoryPoint]
    # the points where the state itself changed
    changes: list[TrustStateChange]


class PublicTrustPage(BaseModel):
    """Public, from an allow-list: no score, no rates, no customer or dispute data"""

    merchant_name: str
    state: TrustState
    label: str
    meaning: str
    # a qualitative sentence, e.g. "Reconciles most of its Paystack payments ..."
    verification_summary: str
    # "based on N payments over the last 30 days"
    payments_30d: int
    window_days: int
    updated_at: datetime | None
    stable_since: datetime | None


class PublicTrustBadge(BaseModel):
    merchant_name: str
    state: TrustState
    label: str
    verified_since: datetime | None
    updated_at: datetime | None
