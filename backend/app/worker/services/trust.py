"""Recomputes a merchant's trust profile from their records (three queries: the lock aside,
the aggregates and the month's readiness facts) and records a snapshot whenever the state
or the internal score changes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from sqlalchemy.orm import Session

from app.api.models.enums import TrustState
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.trust import SyncTrustRepository
from app.api.services.readiness import REPEAT_CUSTOMER_PAYMENTS, ReadinessFacts, score_readiness
from app.api.services.trust_policy import (
    DISPUTE_DAYS,
    FULFILLMENT_DAYS,
    READINESS_DAYS,
    RECONCILIATION_DAYS,
    TrustSignals,
    score_for,
    state_for,
)


@dataclass(frozen=True)
class TrustOutcome:
    state: TrustState
    score: int
    previous_state: TrustState | None
    previous_score: int | None
    # a snapshot was written: the state or the score moved (or it is the first run)
    changed: bool


def _percent(part: int, whole: int) -> float | None:
    return part * 100 / whole if whole else None


def compute_signals(session: Session, merchant_id: UUID, now: datetime) -> TrustSignals:
    repo = SyncTrustRepository(session)
    counts: dict = repo.aggregates(
        merchant_id, now, RECONCILIATION_DAYS, FULFILLMENT_DAYS, DISPUTE_DAYS
    )
    facts = repo.readiness_facts(
        merchant_id, now - timedelta(days=READINESS_DAYS), REPEAT_CUSTOMER_PAYMENTS
    )
    readiness: float | None = (
        sum(score_readiness(ReadinessFacts(*values)).score for values in facts.values())
        / len(facts)
        if facts
        else None
    )
    created_at: datetime | None = repo.merchant_created_at(merchant_id)

    return TrustSignals(
        reconciliation_rate=_percent(counts["matched"], counts["payments"]),
        fulfillment_rate=_percent(counts["fulfilled_orders"], counts["completed_orders"]),
        dispute_rate=_percent(counts["disputes"], counts["payments_dispute_window"]),
        dispute_win_rate=_percent(counts["won_disputes"], counts["resolved_disputes"]),
        avg_response_time=counts["response_pct"],
        evidence_readiness=readiness,
        payments_30d=counts["payments"],
        days_on_platform=(now - created_at).days if created_at else 0,
    )


def recompute_trust_profile(session: Session, merchant_id: UUID, reason: str) -> TrustOutcome:
    """Signals -> state and score -> profile; a snapshot when either moved. Commits"""
    repo = SyncTrustRepository(session)
    repo.lock(merchant_id)
    now: datetime = datetime.now(UTC)

    signals: TrustSignals = compute_signals(session, merchant_id, now)
    state: TrustState = state_for(signals)
    score: int = score_for(signals)

    profile: TrustProfile = repo.profile_for_update(merchant_id)
    first_run: bool = profile.last_computed_at is None
    previous_state: TrustState | None = None if first_run else profile.current_state
    previous_score: int | None = profile.internal_score
    changed: bool = first_run or state != previous_state or score != previous_score

    profile.current_state = state
    profile.internal_score = score
    profile.reconciliation_rate = signals.reconciliation_rate
    profile.fulfillment_rate = signals.fulfillment_rate
    profile.dispute_rate = signals.dispute_rate
    profile.dispute_win_rate = signals.dispute_win_rate
    profile.avg_response_time_pct = signals.avg_response_time
    profile.evidence_readiness_avg = signals.evidence_readiness
    profile.payments_30d = signals.payments_30d
    profile.days_on_platform = signals.days_on_platform
    profile.last_computed_at = now

    if changed:
        repo.add_snapshot(
            TrustSnapshot(
                merchant_id=merchant_id,
                state=state,
                internal_score=score,
                signals=signals.as_dict(),
                reason=reason[:255],
                created_at=now,
            )
        )
    session.commit()

    if changed:
        sentry_logger.info(
            "Trust for merchant {merchant_id}: {previous} -> {state}, score {score} ({reason})",
            merchant_id=str(merchant_id),
            previous=str(previous_state),
            state=state.value,
            score=score,
            reason=reason,
        )
    return TrustOutcome(state, score, previous_state, previous_score, changed)
