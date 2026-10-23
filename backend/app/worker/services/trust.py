"""Recomputes a merchant's trust profile from their records (three queries: the lock aside,
the aggregates and the month's readiness facts) and records a snapshot whenever the state
or the internal score changes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sentry_sdk.logger as sentry_logger
from sqlalchemy.orm import Session

from app.api.models.enums import TrustState
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.ai_memory import SyncAiMemoryRepository
from app.api.repo.trust import SyncTrustRepository
from app.core.config import get_settings
from app.api.services.readiness import REPEAT_CUSTOMER_PAYMENTS, ReadinessFacts, score_readiness
from app.api.services.trust_policy import (
    BUILDING,
    DISPUTE_DAYS,
    FULFILLMENT_DAYS,
    NEW_BELOW_DAYS,
    NEW_BELOW_PAYMENTS,
    READINESS_DAYS,
    RECONCILIATION_DAYS,
    REVIEW,
    VERIFIED,
    VERIFIED_MIN_PAYMENTS,
    TrustSignals,
    score_for,
    state_for,
)

# backend -> ai jobs for trust (the ai worker's handlers of the same names)
TRUST_EXPLAIN: str = "ai:trust:explain"
TRUST_STATE_CHANGE: str = "ai:trust:state-change"

# profile column -> the signal key the ai (and the api) use
SIGNAL_COLUMNS: dict[str, str] = {
    "reconciliation_rate": "reconciliation_rate",
    "fulfillment_rate": "fulfillment_rate",
    "dispute_rate": "dispute_rate",
    "dispute_win_rate": "dispute_win_rate",
    "avg_response_time": "avg_response_time_pct",
    "evidence_readiness": "evidence_readiness_avg",
}


@dataclass(frozen=True)
class AiJob:
    event: str
    job_id: str
    payload: dict


@dataclass(frozen=True)
class TrustOutcome:
    state: TrustState
    score: int
    previous_state: TrustState | None
    previous_score: int | None
    # a snapshot was written: the state or the score moved (or it is the first run)
    changed: bool
    # to send once committed: the explanation, and a summary of a state change
    ai_jobs: tuple[AiJob, ...] = ()


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _profile_signals(profile: TrustProfile) -> dict[str, float | None]:
    return {key: _rounded(getattr(profile, column)) for key, column in SIGNAL_COLUMNS.items()}


def _policy_thresholds() -> dict:
    """The thresholds each state requires, for the ai to quote (never to decide with)"""
    return {
        "verified": {
            **{key: f"at least {value:g}%" for key, value in VERIFIED.items()},
            "dispute_rate": f"at most {VERIFIED['dispute_rate']:g}%",
            "dispute_win_rate": f"at least {VERIFIED['dispute_win_rate']:g}% (or none resolved)",
            "payments_30d": f"at least {VERIFIED_MIN_PAYMENTS}",
        },
        "building": {
            **{key: f"at least {value:g}%" for key, value in BUILDING.items()},
            "dispute_rate": f"at most {BUILDING['dispute_rate']:g}%",
        },
        "review_when_any": {
            "dispute_rate": f"above {REVIEW['dispute_rate']:g}%",
            "fulfillment_rate": f"below {REVIEW['fulfillment_rate']:g}%",
            "reconciliation_rate": f"below {REVIEW['reconciliation_rate']:g}%",
        },
        "minimum_sample": {
            "payments_30d": f"at least {NEW_BELOW_PAYMENTS}",
            "days_on_platform": f"at least {NEW_BELOW_DAYS}",
        },
    }


def _percent(part: int, whole: int) -> float | None:
    return part * 100 / whole if whole else None


def compute_signals(session: Session, merchant_id: UUID, now: datetime) -> TrustSignals:
    repo = SyncTrustRepository(session)
    memory_repo = SyncAiMemoryRepository(session)
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
    previous_signals: dict[str, float | None] = _profile_signals(profile)
    previous_sample: dict[str, int | None] = {
        "payments_30d": profile.payments_30d,
        "days_on_platform": profile.days_on_platform,
    }
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

    jobs: list[AiJob] = []
    if changed:
        snapshot: TrustSnapshot = repo.add_snapshot(
            TrustSnapshot(
                merchant_id=merchant_id,
                state=state,
                internal_score=score,
                signals=signals.as_dict(),
                reason=reason[:255],
                created_at=now,
            )
        )
        session.flush()

        # Materialize every source snapshot once. Storage is unbounded; only the request
        # context is bounded by AI_MEMORY_CONTEXT_LIMIT.
        for item in repo.all_snapshots(merchant_id):
            memory_repo.remember(
                tenant_id=merchant_id,
                merchant_id=merchant_id,
                memory_type="trust_snapshot",
                source_type="trust_snapshot",
                source_id=str(item.id),
                content={
                    "state": item.state.value,
                    "internal_score": item.internal_score,
                    "signals": item.signals,
                    "reason": item.reason,
                    "summary": item.summary,
                },
                occurred_at=item.created_at,
            )
        session.flush()

        # a fresh explanation of the new profile; an answer to an older job is ignored
        explain_id: str = str(uuid4())
        profile.explain_job_id = explain_id
        sample: dict[str, int] = {
            "payments_30d": signals.payments_30d,
            "days_on_platform": signals.days_on_platform,
        }
        jobs.append(
            AiJob(
                TRUST_EXPLAIN,
                explain_id,
                {
                    "merchantId": str(merchant_id),
                    "currentState": state.value,
                    "signals": _profile_signals(profile),
                    "sample": sample,
                    "policyThresholds": _policy_thresholds(),
                    "memory": {
                        "previousExplanation": profile.explanation,
                        "previousRecommendations": profile.recommendations or [],
                        "recentMemories": [
                            {
                                "source_type": item.source_type,
                                "source_id": item.source_id,
                                "occurred_at": item.occurred_at.isoformat(),
                                "content": item.content,
                            }
                            for item in memory_repo.retrieve(
                                tenant_id=merchant_id,
                                merchant_id=merchant_id,
                                limit=get_settings().AI_MEMORY_CONTEXT_LIMIT,
                            )
                        ],
                    },
                },
            )
        )

        # the state itself moved: a one-line account for the history (keyed by snapshot)
        if previous_state is not None and state != previous_state:
            current: dict[str, float | None] = _profile_signals(profile)
            diff: dict[str, dict] = {
                key: {"before": previous_signals[key], "after": value}
                for key, value in current.items()
                if previous_signals[key] != value
            }
            for key, value in sample.items():
                if previous_sample[key] != value:
                    diff[key] = {"before": previous_sample[key], "after": value}
            jobs.append(
                AiJob(
                    TRUST_STATE_CHANGE,
                    str(snapshot.id),
                    {
                        "merchantId": str(merchant_id),
                        "previousState": previous_state.value,
                        "newState": state.value,
                        "signalDiff": diff,
                    },
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
    return TrustOutcome(state, score, previous_state, previous_score, changed, tuple(jobs))
