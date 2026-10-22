"""Dashboard queries: one aggregate row for the metrics, and one query per block. Counts
only: no money is summed anywhere."""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    DATE,
    Select,
    Text,
    cast,
    exists,
    func,
    literal,
    null,
    select,
    union_all,
)

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeStatus,
    OrderStatus,
    ReconciliationSessionStatus,
    ReconciliationStatus,
    TransactionStatus,
)
from app.api.models.fulfillments import Fulfillment
from app.api.models.orders import Order
from app.api.models.reconciliation_sessions import ReconciliationSession
from app.api.models.transactions import Transaction
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.base import BaseRepository
from app.api.repo.disputes import AWAITING_STATUSES, CRITICAL_HOURS
from app.api.repo.readiness import ReadinessRepository

MATCHED = (ReconciliationStatus.AUTO_MATCHED, ReconciliationStatus.MANUALLY_MATCHED)
RESOLVED = (DisputeStatus.WON, DisputeStatus.LOST, DisputeStatus.AUTO_ACCEPTED)
# the critical dispute block shows the soonest dispute due within this many hours
CRITICAL_BLOCK_HOURS: int = 8
# each source contributes at most this many rows before the feed is merged and cut
ACTIVITY_PER_SOURCE: int = 10


def _local_day(column, zone: str):
    """The day a timestamp falls on in the merchant's timezone"""
    return cast(func.timezone(zone, column), DATE)


class DashboardRepository(BaseRepository[BaseModel, Transaction]):
    model = Transaction

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return Transaction(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        return []

    async def metrics(
        self,
        merchant_id: UUID,
        period: tuple[datetime, datetime],
        previous: tuple[datetime, datetime],
        now: datetime,
    ) -> dict[str, int]:
        """Every metric count in one row. Periods are [start, end)"""

        def payments(*conditions) -> Any:
            return (
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.merchant_id == merchant_id, *conditions)
                .scalar_subquery()
            )

        def disputes(*conditions) -> Any:
            return (
                select(func.count())
                .select_from(Dispute)
                .where(Dispute.merchant_id == merchant_id, *conditions)
                .scalar_subquery()
            )

        success = Transaction.status == TransactionStatus.SUCCESS
        matched = (
            Transaction.order_id.is_not(None),
            Transaction.reconciliation_status.in_(MATCHED),
        )

        def started_in(window: tuple[datetime, datetime]):
            return (
                Transaction.paystack_created_at >= window[0],
                Transaction.paystack_created_at < window[1],
            )

        def paid_in(window: tuple[datetime, datetime]):
            return Transaction.paid_at >= window[0], Transaction.paid_at < window[1]

        awaiting = Dispute.status.in_(AWAITING_STATUSES)
        row = (
            await self._async_session.execute(
                select(
                    payments(*started_in(period)).label("attempts"),
                    payments(success, *started_in(period)).label("successful"),
                    payments(success, *started_in(previous)).label("previous_successful"),
                    payments(success, *paid_in(period)).label("paid"),
                    payments(success, *paid_in(period), *matched).label("matched"),
                    payments(success, *paid_in(previous)).label("previous_paid"),
                    payments(success, *paid_in(previous), *matched).label("previous_matched"),
                    payments(
                        success,
                        Transaction.order_id.is_(None),
                        Transaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
                    ).label("unmatched"),
                    disputes(awaiting).label("open"),
                    disputes(
                        awaiting,
                        Dispute.due_at > now,
                        Dispute.due_at < now + timedelta(hours=CRITICAL_HOURS),
                    ).label("critical"),
                    disputes(Dispute.created_at >= period[0], Dispute.created_at < period[1]).label(
                        "opened"
                    ),
                    disputes(
                        Dispute.status.in_(RESOLVED),
                        Dispute.resolved_at >= period[0],
                        Dispute.resolved_at < period[1],
                    ).label("resolved"),
                )
            )
        ).one()
        return dict(row._mapping)

    async def readiness_facts(
        self, merchant_id: UUID, period: tuple[datetime, datetime], repeat_payments: int
    ) -> dict[UUID, tuple[bool, ...]]:
        """Readiness facts of the period's matched payments, in one query"""
        ids = select(Transaction.id).where(
            Transaction.merchant_id == merchant_id,
            Transaction.status == TransactionStatus.SUCCESS,
            Transaction.paid_at >= period[0],
            Transaction.paid_at < period[1],
            Transaction.order_id.is_not(None),
            Transaction.reconciliation_status.in_(MATCHED),
        )
        rows = await self._async_session.execute(
            ReadinessRepository.evidence_statement(ids, repeat_payments)
        )
        return ReadinessRepository.to_facts(rows.all())

    async def critical_dispute(self, merchant_id: UUID, now: datetime):
        """The soonest dispute awaiting the merchant and due within CRITICAL_BLOCK_HOURS"""
        return (
            await self._async_session.execute(
                select(
                    Dispute.id,
                    Dispute.paystack_dispute_id,
                    Dispute.amount,
                    Dispute.currency,
                    Dispute.due_at,
                    func.coalesce(Transaction.customer_name, Customer.name).label("customer_name"),
                )
                .join(Transaction, Transaction.id == Dispute.transaction_id)
                .outerjoin(Customer, Customer.id == Transaction.customer_id)
                .where(
                    Dispute.merchant_id == merchant_id,
                    Dispute.status.in_(AWAITING_STATUSES),
                    Dispute.due_at > now,
                    Dispute.due_at < now + timedelta(hours=CRITICAL_BLOCK_HOURS),
                )
                .order_by(Dispute.due_at)
                .limit(1)
            )
        ).one_or_none()

    async def unfulfilled_paid_orders(self, merchant_id: UUID, limit: int) -> list:
        return list(
            await self._async_session.execute(
                select(Order.id, Order.order_number, Order.amount, Order.currency)
                .where(
                    Order.merchant_id == merchant_id,
                    Order.status == OrderStatus.PAID,
                    ~exists().where(Fulfillment.order_id == Order.id),
                )
                .order_by(Order.ordered_at.desc(), Order.id.desc())
                .limit(limit)
            )
        )

    async def activity(self, merchant_id: UUID, limit: int) -> list:
        """What happened lately, derived from the records: (type, occurred_at, record id,
        amount, currency, detail) rows, newest first"""

        def source(
            kind,
            occurred_at,
            record_id,
            table_conditions: list,
            amount=None,
            currency=None,
            detail=None,
            from_=None,
        ) -> Select:
            stmt = select(
                kind.label("type"),
                occurred_at.label("occurred_at"),
                record_id.label("record_id"),
                (amount if amount is not None else null()).label("amount"),
                (currency if currency is not None else null()).label("currency"),
                (detail if detail is not None else null()).label("detail"),
            )
            if from_ is not None:
                stmt = stmt.select_from(from_)
            return (
                stmt.where(occurred_at.is_not(None), *table_conditions)
                .order_by(occurred_at.desc())
                .limit(ACTIVITY_PER_SOURCE)
            )

        mine = Dispute.merchant_id == merchant_id
        previous_state = (
            func.lag(TrustSnapshot.state)
            .over(partition_by=TrustSnapshot.merchant_id, order_by=TrustSnapshot.created_at)
            .label("previous_state")
        )
        snapshots = (
            select(
                TrustSnapshot.id,
                TrustSnapshot.created_at,
                TrustSnapshot.state,
                previous_state,
            )
            .where(TrustSnapshot.merchant_id == merchant_id)
            .subquery("snapshots")
        )

        sources: list[Select] = [
            source(
                literal("dispute_created"),
                Dispute.created_at,
                Dispute.id,
                [mine],
                Dispute.amount,
                cast(Dispute.currency, Text),
            ),
            source(
                literal("dispute_submitted"),
                Dispute.submitted_at,
                Dispute.id,
                [mine, Dispute.status != DisputeStatus.PENDING],
                Dispute.amount,
                cast(Dispute.currency, Text),
            ),
            source(
                func.concat("dispute_", cast(Dispute.status, Text)),
                Dispute.resolved_at,
                Dispute.id,
                [mine, Dispute.status.in_(RESOLVED)],
                Dispute.amount,
                cast(Dispute.currency, Text),
            ),
            source(
                literal("fulfillment_logged"),
                Fulfillment.created_at,
                Order.id,
                [Fulfillment.merchant_id == merchant_id],
                detail=Order.order_number,
                from_=Fulfillment.__table__.join(Order.__table__, Order.id == Fulfillment.order_id),
            ),
            source(
                literal("reconciliation_completed"),
                ReconciliationSession.completed_at,
                ReconciliationSession.id,
                [
                    ReconciliationSession.merchant_id == merchant_id,
                    ReconciliationSession.status == ReconciliationSessionStatus.COMPLETED,
                ],
                amount=ReconciliationSession.matched_count,
            ),
            source(
                literal("trust_changed"),
                snapshots.c.created_at,
                snapshots.c.id,
                [
                    snapshots.c.previous_state.is_not(None),
                    snapshots.c.state != snapshots.c.previous_state,
                ],
                detail=func.concat(
                    cast(snapshots.c.previous_state, Text),
                    ">",
                    cast(snapshots.c.state, Text),
                ),
            ),
        ]

        merged = union_all(*sources).subquery("activity")
        return list(
            await self._async_session.execute(
                select(merged).order_by(merged.c.occurred_at.desc()).limit(limit)
            )
        )

    async def dispute_timeline(self, merchant_id: UUID, zone: str, since: datetime) -> list:
        """Per local day: opened, won, lost and auto-accepted"""
        opened = select(
            _local_day(Dispute.created_at, zone).label("day"),
            literal("opened").label("kind"),
        ).where(Dispute.merchant_id == merchant_id, Dispute.created_at >= since)
        resolved = select(
            _local_day(Dispute.resolved_at, zone).label("day"),
            cast(Dispute.status, Text).label("kind"),
        ).where(
            Dispute.merchant_id == merchant_id,
            Dispute.status.in_(RESOLVED),
            Dispute.resolved_at >= since,
        )
        events = union_all(opened, resolved).subquery("events")
        return list(
            await self._async_session.execute(
                select(events.c.day, events.c.kind, func.count()).group_by(
                    events.c.day, events.c.kind
                )
            )
        )

    async def session_health(self, merchant_id: UUID, since: datetime):
        return (
            await self._async_session.execute(
                select(
                    func.count().label("started"),
                    func.count()
                    .filter(ReconciliationSession.status == ReconciliationSessionStatus.COMPLETED)
                    .label("completed"),
                    func.avg(
                        ReconciliationSession.unmatched_payments_count
                        + ReconciliationSession.unmatched_orders_count
                        + ReconciliationSession.flagged_count
                    )
                    .filter(ReconciliationSession.status == ReconciliationSessionStatus.COMPLETED)
                    .label("avg_mismatches"),
                ).where(
                    ReconciliationSession.merchant_id == merchant_id,
                    ReconciliationSession.created_at >= since,
                )
            )
        ).one()

    async def match_rate_series(self, merchant_id: UUID, zone: str, since: datetime) -> list:
        """Per local day of payment: successful payments and those matched"""
        day = _local_day(Transaction.paid_at, zone)
        return list(
            await self._async_session.execute(
                select(
                    day.label("day"),
                    func.count(),
                    func.count().filter(
                        Transaction.order_id.is_not(None),
                        Transaction.reconciliation_status.in_(MATCHED),
                    ),
                )
                .where(
                    Transaction.merchant_id == merchant_id,
                    Transaction.status == TransactionStatus.SUCCESS,
                    Transaction.paid_at >= since,
                )
                .group_by(day)
            )
        )


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
