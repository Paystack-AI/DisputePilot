"""The TrustLayer policy (project path section 19): deterministic, no ai.

Six signals from existing data, a state from fixed thresholds, and an internal 0-100 score
(merchant-only, never public). Every threshold and weight is here so the policy can be
quoted and changed in one place.
"""

from dataclasses import asdict, dataclass

from app.api.models.enums import TrustState

RECONCILIATION_DAYS: int = 30
FULFILLMENT_DAYS: int = 30
DISPUTE_DAYS: int = 90
READINESS_DAYS: int = 30
# the response window disputes are measured against (paystack's ~16 hours)
RESPONSE_WINDOW_HOURS: int = 16

# minimum sample: below it the state is new whatever the signals say
NEW_BELOW_PAYMENTS: int = 10
NEW_BELOW_DAYS: int = 14
VERIFIED_MIN_PAYMENTS: int = 30

VERIFIED: dict[str, float] = {
    "reconciliation_rate": 80,
    "fulfillment_rate": 70,
    "dispute_rate": 2,  # at most
    "dispute_win_rate": 60,  # or no resolved disputes
}
BUILDING: dict[str, float] = {
    "reconciliation_rate": 50,
    "fulfillment_rate": 40,
    "dispute_rate": 5,  # at most
}
REVIEW: dict[str, float] = {
    "dispute_rate": 5,  # above
    "fulfillment_rate": 30,  # below
    "reconciliation_rate": 40,  # below
}

# internal score weights (sum 100); dispute rate and response time count inverted
WEIGHTS: dict[str, int] = {
    "reconciliation_rate": 25,
    "fulfillment_rate": 25,
    "dispute_rate": 20,
    "dispute_win_rate": 15,
    "evidence_readiness": 10,
    "avg_response_time": 5,
}
# a dispute rate at or above this scores 0 on its component
DISPUTE_RATE_FLOOR: float = 5


@dataclass(frozen=True)
class TrustSignals:
    """Percentages (0-100); None when there is nothing to measure yet"""

    reconciliation_rate: float | None
    fulfillment_rate: float | None
    dispute_rate: float | None
    dispute_win_rate: float | None  # None: no resolved disputes
    avg_response_time: float | None  # None: never responded
    evidence_readiness: float | None
    # sample
    payments_30d: int
    days_on_platform: int

    def as_dict(self) -> dict:
        return {
            key: (round(value, 2) if isinstance(value, float) else value)
            for key, value in asdict(self).items()
        }


def _value(value: float | None) -> float:
    """A missing rate counts as zero against a minimum (no orders fulfilled is 0%)"""
    return value or 0.0


def min_sample_met(signals: TrustSignals) -> bool:
    return signals.payments_30d >= NEW_BELOW_PAYMENTS and signals.days_on_platform >= NEW_BELOW_DAYS


def meets_verified(signals: TrustSignals) -> bool:
    return (
        signals.payments_30d >= VERIFIED_MIN_PAYMENTS
        and _value(signals.reconciliation_rate) >= VERIFIED["reconciliation_rate"]
        and _value(signals.fulfillment_rate) >= VERIFIED["fulfillment_rate"]
        and _value(signals.dispute_rate) <= VERIFIED["dispute_rate"]
        and (
            signals.dispute_win_rate is None
            or signals.dispute_win_rate >= VERIFIED["dispute_win_rate"]
        )
    )


def meets_building(signals: TrustSignals) -> bool:
    return (
        _value(signals.reconciliation_rate) >= BUILDING["reconciliation_rate"]
        and _value(signals.fulfillment_rate) >= BUILDING["fulfillment_rate"]
        and _value(signals.dispute_rate) <= BUILDING["dispute_rate"]
    )


def state_for(signals: TrustSignals) -> TrustState:
    """new before the minimum sample, then the best state the signals meet. Falling
    between building and the review thresholds is review too: not shown publicly"""
    if not min_sample_met(signals):
        return TrustState.NEW
    if meets_verified(signals):
        return TrustState.VERIFIED
    if meets_building(signals):
        return TrustState.BUILDING
    return TrustState.REVIEW


def score_for(signals: TrustSignals) -> int:
    """0-100, for the merchant only"""
    dispute_rate: float = _value(signals.dispute_rate)
    components: dict[str, float] = {
        "reconciliation_rate": _value(signals.reconciliation_rate),
        "fulfillment_rate": _value(signals.fulfillment_rate),
        "dispute_rate": max(0.0, 100 - dispute_rate * 100 / DISPUTE_RATE_FLOOR),
        # no disputes to lose, or none answered late: nothing against the merchant
        "dispute_win_rate": 100.0 if signals.dispute_win_rate is None else signals.dispute_win_rate,
        "evidence_readiness": _value(signals.evidence_readiness),
        "avg_response_time": (
            100.0 if signals.avg_response_time is None else 100 - signals.avg_response_time
        ),
    }
    total: float = sum(
        min(max(components[key], 0.0), 100.0) * weight / 100 for key, weight in WEIGHTS.items()
    )
    return round(total)


def reading(key: str, value: float | None) -> str:
    """strong (meets verified), fair (meets building) or weak, for one signal; insufficient
    when there is nothing to measure"""
    if key == "dispute_win_rate":
        if value is None:
            return "insufficient"
        return "strong" if value >= VERIFIED["dispute_win_rate"] else "weak"
    if key == "dispute_rate":
        if value is None:
            return "insufficient"
        if value <= VERIFIED["dispute_rate"]:
            return "strong"
        return "fair" if value <= BUILDING["dispute_rate"] else "weak"
    if key in ("reconciliation_rate", "fulfillment_rate"):
        if value is None:
            return "insufficient"
        if value >= VERIFIED[key]:
            return "strong"
        return "fair" if value >= BUILDING[key] else "weak"
    # readiness and response time have no state thresholds; bands from their own scales
    if value is None:
        return "insufficient"
    if key == "avg_response_time":
        return "strong" if value <= 50 else "fair" if value <= 85 else "weak"
    return "strong" if value >= 70 else "fair" if value >= 40 else "weak"
