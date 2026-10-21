"""The dashboard: one call for the first paint, plus the two chart endpoints.

Every block is built in its own savepoint, so a block that fails is null and the rest of
the page still renders. Counts and states only: money appears on individual records,
never summed (no revenue, payout or settlement figures).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis

from app.api.models.enums import Currency
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.repo.dashboard import DashboardRepository, days_between
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.repo.reconciliation import ReconciliationRepository
from app.api.repo.trust import TrustRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.dashboard import (
    DEFAULT_PERIOD_DAYS,
    ActivityItem,
    ActivityLink,
    CriticalDispute,
    Dashboard,
    DashboardMetrics,
    DashboardQuery,
    DisputeMetrics,
    DisputeTimeline,
    DisputeTimelineDay,
    FulfillmentPrompt,
    MatchRateDay,
    Period,
    ReadinessMetrics,
    ReconciliationBlock,
    ReconciliationHealth,
    ReconciliationMetrics,
    TransactionMetrics,
    TrustBlock,
)
from app.api.schemas.disputes import DisputeListQuery
from app.api.schemas.transactions import TransactionListQuery
from app.api.services.disputes import DisputeService
from app.api.services.readiness import (
    REPEAT_CUSTOMER_PAYMENTS,
    ReadinessFacts,
    label_for,
    score_readiness,
)
from app.api.services.transactions import TransactionService
from app.api.services.trust import LABELS

T = TypeVar("T")

RECENT: int = 5
PROMPTS: int = 5
ACTIVITY: int = 10
# needs_review in the reconciliation block looks this far back (as /reconciliation/summary)
REVIEW_DAYS: int = 30


def _day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


def _zone(settings: MerchantSettings | None) -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone if settings and settings.timezone else "UTC")
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _money(amount: int | None, currency: str | None) -> str:
    if amount is None or not currency:
        return ""
    return f"{currency} {amount / 100:,.2f}"


def _activity_item(row) -> ActivityItem | None:
    kind: str = row.type
    money: str = _money(row.amount, row.currency)
    if kind == "dispute_created":
        title, link = f"New dispute for {money}", ActivityLink(type="dispute", id=row.record_id)
    elif kind == "dispute_submitted":
        title, link = (
            f"Response submitted for {money}",
            ActivityLink(type="dispute", id=row.record_id),
        )
    elif kind in ("dispute_won", "dispute_lost", "dispute_auto_accepted"):
        outcome: str = {
            "dispute_won": "won",
            "dispute_lost": "lost",
            "dispute_auto_accepted": "refunded (no response in time)",
        }[kind]
        title, link = (
            f"Dispute for {money} {outcome}",
            ActivityLink(type="dispute", id=row.record_id),
        )
    elif kind == "fulfillment_logged":
        order: str = f"order {row.detail}" if row.detail else "an order"
        title, link = (
            f"Fulfillment logged for {order}",
            ActivityLink(type="order", id=row.record_id),
        )
    elif kind == "reconciliation_completed":
        title = f"Reconciliation completed: {row.amount or 0} matched"
        link = ActivityLink(type="reconciliation_session", id=row.record_id)
    elif kind == "trust_changed":
        before, _, after = (row.detail or ">").partition(">")
        title = f"Trust state changed: {before.capitalize()} to {after.capitalize()}"
        link = ActivityLink(type="trust", id=None)
    else:
        return None
    return ActivityItem(type=kind, occurred_at=row.occurred_at, title=title, link=link)


class DashboardService:
    def __init__(self, redis: Redis):
        self._redis = redis

    def _setup(self, uow: UnitOfWorkRepository):
        self._uow = uow
        self._repo = uow.repo(DashboardRepository)

    async def _block(
        self, name: str, merchant_id: UUID, build: Callable[[], Awaitable[T]]
    ) -> T | None:
        """A block in its own savepoint: a failure rolls back only the block and leaves it
        null"""
        try:
            async with self._uow.async_session.begin_nested():
                return await build()
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Dashboard block {block} failed for merchant {merchant_id}",
                block=name,
                merchant_id=str(merchant_id),
            )
            return None

    async def _settings(self, merchant_id: UUID) -> MerchantSettings | None:
        return await self._uow.repo(MerchantSettingsRepository).get_record(merchant_id=merchant_id)

    @staticmethod
    def _period(query: DashboardQuery, zone: ZoneInfo) -> Period:
        today: date = datetime.now(zone).date()
        date_from: date = query.date_from or today - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
        date_to: date = query.date_to or today
        length: int = (date_to - date_from).days + 1
        return Period(
            date_from=date_from,
            date_to=date_to,
            previous_from=date_from - timedelta(days=length),
            previous_to=date_from - timedelta(days=1),
        )

    # ------------------------------ blocks ------------------------------ #

    async def _metrics(
        self,
        merchant_id: UUID,
        window: tuple[datetime, datetime],
        previous: tuple[datetime, datetime],
        now: datetime,
    ) -> DashboardMetrics:
        counts: dict = await self._repo.metrics(merchant_id, window, previous, now)
        facts = await self._repo.readiness_facts(merchant_id, window, REPEAT_CUSTOMER_PAYMENTS)

        scores: list[int] = [score_readiness(ReadinessFacts(*f)).score for f in facts.values()]
        distribution: dict[str, int] = {"well_defended": 0, "moderate": 0, "vulnerable": 0}
        for score in scores:
            distribution[label_for(score)] += 1
        average: int | None = round(sum(scores) / len(scores)) if scores else None

        matched_pct: float | None = _pct(counts["matched"], counts["paid"])
        previous_pct: float | None = _pct(counts["previous_matched"], counts["previous_paid"])

        return DashboardMetrics(
            transactions=TransactionMetrics(
                count=counts["attempts"],
                successful=counts["successful"],
                delta_pct=(
                    round(
                        (counts["successful"] - counts["previous_successful"])
                        * 100
                        / counts["previous_successful"],
                        1,
                    )
                    if counts["previous_successful"]
                    else None
                ),
            ),
            disputes=DisputeMetrics(
                open=counts["open"],
                critical=counts["critical"],
                opened=counts["opened"],
                resolved=counts["resolved"],
            ),
            readiness=ReadinessMetrics(
                score=average,
                label=label_for(average) if average is not None else None,
                distribution={
                    label: round(count * 100 / len(scores)) if scores else 0
                    for label, count in distribution.items()
                },
            ),
            reconciliation=ReconciliationMetrics(
                matched_pct=matched_pct,
                unmatched=counts["unmatched"],
                delta_pct=(
                    round(matched_pct - previous_pct, 1)
                    if matched_pct is not None and previous_pct is not None
                    else None
                ),
            ),
        )

    async def _critical(self, merchant_id: UUID, now: datetime) -> CriticalDispute | None:
        row = await self._repo.critical_dispute(merchant_id, now)
        if not row:
            return None
        return CriticalDispute(
            id=row.id,
            paystack_dispute_id=str(row.paystack_dispute_id),
            amount=row.amount,
            currency=row.currency,
            due_at=row.due_at,
            customer_name=row.customer_name,
        )

    async def _reconciliation(self, merchant_id: UUID, zone: ZoneInfo) -> ReconciliationBlock:
        repo: ReconciliationRepository = self._uow.repo(ReconciliationRepository)
        synced, matched, needs_review = await repo.summary_counts(
            merchant_id,
            _day_start(datetime.now(zone).date(), zone),
            datetime.now(UTC) - timedelta(days=REVIEW_DAYS),
        )
        return ReconciliationBlock(
            synced_today=synced,
            matched_today=matched,
            needs_review=needs_review,
            last_completed_at=await repo.last_completed_at(merchant_id),
        )

    async def _trust(self, merchant_id: UUID) -> TrustBlock | None:
        profile = await self._uow.repo(TrustRepository).get_record(merchant_id=merchant_id)
        if not profile:
            return None
        return TrustBlock(
            state=profile.current_state,
            label=LABELS[profile.current_state],
            updated_at=profile.last_computed_at,
        )

    async def _prompts(self, merchant_id: UUID) -> list[FulfillmentPrompt]:
        return [
            FulfillmentPrompt(
                order_id=row.id,
                order_number=row.order_number,
                amount=row.amount,
                currency=row.currency,
            )
            for row in await self._repo.unfulfilled_paid_orders(merchant_id, PROMPTS)
        ]

    async def _activity(self, merchant_id: UUID) -> list[ActivityItem]:
        items = [_activity_item(row) for row in await self._repo.activity(merchant_id, ACTIVITY)]
        return [item for item in items if item]

    # ------------------------------ endpoints ------------------------------ #

    async def dashboard(
        self, merchant: Merchant, query: DashboardQuery, uow: UnitOfWorkRepository
    ) -> Dashboard:
        self._setup(uow)
        merchant_id: UUID = merchant.id
        now: datetime = datetime.now(UTC)
        settings: MerchantSettings | None = await self._settings(merchant_id)
        zone: ZoneInfo = _zone(settings)
        period: Period = self._period(query, zone)
        window = (
            _day_start(period.date_from, zone),
            _day_start(period.date_to + timedelta(days=1), zone),
        )
        previous = (
            _day_start(period.previous_from, zone),
            _day_start(period.previous_to + timedelta(days=1), zone),
        )

        metrics: DashboardMetrics | None = await self._block(
            "metrics", merchant_id, lambda: self._metrics(merchant_id, window, previous, now)
        )
        recent_transactions = await self._block(
            "recent_transactions",
            merchant_id,
            lambda: TransactionService().list_transactions(
                merchant, TransactionListQuery(limit=RECENT), uow
            ),
        )
        recent_disputes = await self._block(
            "recent_disputes",
            merchant_id,
            lambda: DisputeService(self._redis).list_disputes(
                merchant, DisputeListQuery(limit=RECENT), uow
            ),
        )

        return Dashboard(
            server_time=now,
            currency=settings.default_currency if settings else Currency.NGN,
            period=period,
            metrics=metrics
            or DashboardMetrics(
                transactions=None, disputes=None, readiness=None, reconciliation=None
            ),
            critical_dispute=await self._block(
                "critical_dispute", merchant_id, lambda: self._critical(merchant_id, now)
            ),
            reconciliation=await self._block(
                "reconciliation", merchant_id, lambda: self._reconciliation(merchant_id, zone)
            ),
            trust=await self._block("trust", merchant_id, lambda: self._trust(merchant_id)),
            prompts=await self._block("prompts", merchant_id, lambda: self._prompts(merchant_id)),
            recent_transactions=recent_transactions[0] if recent_transactions else None,
            recent_disputes=recent_disputes[0] if recent_disputes else None,
            activity=await self._block(
                "activity", merchant_id, lambda: self._activity(merchant_id)
            ),
        )

    async def dispute_timeline(
        self, merchant: Merchant, days: int, uow: UnitOfWorkRepository
    ) -> DisputeTimeline:
        self._setup(uow)
        zone: ZoneInfo = _zone(await self._settings(merchant.id))
        today: date = datetime.now(zone).date()
        first: date = today - timedelta(days=days - 1)

        counts: dict[date, dict[str, int]] = {}
        for day, kind, count in await self._repo.dispute_timeline(
            merchant.id, str(zone), _day_start(first, zone)
        ):
            counts.setdefault(day, {})[kind] = count

        return DisputeTimeline(
            days=days,
            series=[
                DisputeTimelineDay(
                    date=day,
                    opened=counts.get(day, {}).get("opened", 0),
                    won=counts.get(day, {}).get("won", 0),
                    lost=counts.get(day, {}).get("lost", 0),
                    auto_accepted=counts.get(day, {}).get("auto_accepted", 0),
                )
                for day in days_between(first, today)
            ],
        )

    async def reconciliation_health(
        self, merchant: Merchant, days: int, uow: UnitOfWorkRepository
    ) -> ReconciliationHealth:
        self._setup(uow)
        zone: ZoneInfo = _zone(await self._settings(merchant.id))
        today: date = datetime.now(zone).date()
        first: date = today - timedelta(days=days - 1)
        since: datetime = _day_start(first, zone)

        sessions = await self._repo.session_health(merchant.id, since)
        rates: dict[date, tuple[int, int]] = {
            day: (payments, matched)
            for day, payments, matched in await self._repo.match_rate_series(
                merchant.id, str(zone), since
            )
        }

        return ReconciliationHealth(
            days=days,
            sessions_started=sessions.started,
            sessions_completed=sessions.completed,
            completion_rate=_pct(sessions.completed, sessions.started),
            avg_mismatches=(
                round(float(sessions.avg_mismatches), 1)
                if sessions.avg_mismatches is not None
                else None
            ),
            series=[
                MatchRateDay(
                    date=day,
                    payments=rates.get(day, (0, 0))[0],
                    matched=rates.get(day, (0, 0))[1],
                    matched_pct=_pct(rates.get(day, (0, 0))[1], rates.get(day, (0, 0))[0]),
                )
                for day in days_between(first, today)
            ],
        )
