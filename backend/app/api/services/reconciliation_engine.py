"""Runs the matching tiers for a merchant: loads open payments and orders through the
matching repository, plans with matching.plan_matches and writes the plan back. The same
steps run on the api's async repository (sessions) and on celery's sync one (the pass after
every sync). Callers commit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.models.enums import MatchSuggestionStatus
from app.api.repo.matching import MatchingRepository, SyncMatchingRepository
from app.api.services.matching import (
    TIER2_WINDOW,
    TIER3_WINDOW,
    Candidate,
    MatchPlan,
    Payment,
    plan_matches,
)

# the automatic pass after a sync looks this far back, so an order logged after its payment
# synced is still matched on the next sync
AUTO_MATCH_DAYS: int = 30


@dataclass(frozen=True)
class MatchOutcome:
    matched: int = 0
    suggested: int = 0
    flagged: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.matched or self.suggested or self.flagged)

    def as_dict(self) -> dict[str, int]:
        return {"matched": self.matched, "suggested": self.suggested, "flagged": self.flagged}


def _suggestion_rows(merchant_id: UUID, plan: MatchPlan, now: datetime) -> list[dict]:
    return [
        {
            "merchant_id": merchant_id,
            "transaction_id": s.transaction_id,
            "order_id": s.order_id,
            "tier": s.tier,
            "confidence": s.confidence,
            "reason": s.reason,
            "status": MatchSuggestionStatus.PENDING,
            "created_at": now,
        }
        for s in plan.suggestions
    ]


def _outcome(plan: MatchPlan) -> MatchOutcome:
    return MatchOutcome(
        matched=len(plan.matches),
        suggested=len({s.transaction_id for s in plan.suggestions}),
        flagged=len(plan.flags),
    )


async def run_matching(
    repo: MatchingRepository, merchant_id: UUID, paid_from: datetime, paid_to: datetime
) -> MatchOutcome:
    """Match the merchant's open payments paid in [paid_from, paid_to)"""
    await repo.lock(merchant_id)

    payments: list[Payment] = [
        Payment(*row) for row in await repo.open_payments(merchant_id, paid_from, paid_to)
    ]
    if not payments:
        await repo.drop_stale_suggestions(merchant_id)
        return MatchOutcome()

    payment_ids: list[UUID] = [payment.id for payment in payments]
    orders: list[Candidate] = [
        Candidate(*row)
        for row in await repo.open_orders(
            merchant_id, paid_from - TIER2_WINDOW, paid_to + TIER3_WINDOW
        )
    ]
    plan: MatchPlan = plan_matches(
        payments,
        orders,
        await repo.rejected_pairs(merchant_id, payment_ids),
        await repo.tier1_auto(merchant_id),
    )

    now: datetime = datetime.now(UTC)
    for match in plan.matches:
        await repo.link(match.transaction_id, match.order_id, match.tier, match.confidence, now)
    for flag in plan.flags:
        await repo.flag(flag.transaction_id, flag.reason, now)
    await repo.replace_suggestions(
        merchant_id, payment_ids, _suggestion_rows(merchant_id, plan, now)
    )
    await repo.drop_stale_suggestions(merchant_id)

    return _outcome(plan)


def run_matching_sync(
    repo: SyncMatchingRepository, merchant_id: UUID, paid_from: datetime, paid_to: datetime
) -> MatchOutcome:
    """run_matching for celery"""
    repo.lock(merchant_id)

    payments: list[Payment] = [
        Payment(*row) for row in repo.open_payments(merchant_id, paid_from, paid_to)
    ]
    if not payments:
        repo.drop_stale_suggestions(merchant_id)
        return MatchOutcome()

    payment_ids: list[UUID] = [payment.id for payment in payments]
    orders: list[Candidate] = [
        Candidate(*row)
        for row in repo.open_orders(merchant_id, paid_from - TIER2_WINDOW, paid_to + TIER3_WINDOW)
    ]
    plan: MatchPlan = plan_matches(
        payments,
        orders,
        repo.rejected_pairs(merchant_id, payment_ids),
        repo.tier1_auto(merchant_id),
    )

    now: datetime = datetime.now(UTC)
    for match in plan.matches:
        repo.link(match.transaction_id, match.order_id, match.tier, match.confidence, now)
    for flag in plan.flags:
        repo.flag(flag.transaction_id, flag.reason, now)
    repo.replace_suggestions(merchant_id, payment_ids, _suggestion_rows(merchant_id, plan, now))
    repo.drop_stale_suggestions(merchant_id)

    return _outcome(plan)


def auto_match_after_sync(session: Session, merchant_id: UUID) -> MatchOutcome:
    """The automatic pass: every open payment of the last AUTO_MATCH_DAYS days"""
    now: datetime = datetime.now(UTC)
    return run_matching_sync(
        SyncMatchingRepository(session),
        merchant_id,
        now - timedelta(days=AUTO_MATCH_DAYS),
        now + timedelta(seconds=1),
    )
