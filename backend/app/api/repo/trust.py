"""TrustLayer queries. The signals are computed by the worker (SyncTrustRepository), in two
queries: one row of aggregates, and the readiness facts of the month's matched payments.
The api only reads profiles and snapshots (TrustRepository)."""

import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    case,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeStatus,
    OrderStatus,
    ReconciliationStatus,
    TransactionStatus,
    TrustState,
)
from app.api.models.files import StoredFile
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.base import BaseRepository
from app.api.repo.readiness import ReadinessRepository

MATCHED = (ReconciliationStatus.AUTO_MATCHED, ReconciliationStatus.MANUALLY_MATCHED)
RESOLVED = (DisputeStatus.WON, DisputeStatus.LOST, DisputeStatus.AUTO_ACCEPTED)
COMPLETED_ORDERS = (OrderStatus.PAID, OrderStatus.FULFILLED)


def _filled(column):
    return func.coalesce(func.trim(column), "") != ""


def new_public_token() -> str:
    return secrets.token_urlsafe(24)


class SyncTrustRepository:
    def __init__(self, session: Session):
        self._session = session

    def last_computed_at(self, merchant_id: UUID) -> datetime | None:
        return self._session.scalar(
            select(TrustProfile.last_computed_at).where(TrustProfile.merchant_id == merchant_id)
        )

    def lock(self, merchant_id: UUID):
        """Two recomputations of one merchant run one after the other"""
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"trust:{merchant_id}", 0)))
        )

    def merchant_created_at(self, merchant_id: UUID) -> datetime | None:
        return self._session.scalar(select(Merchant.created_at).where(Merchant.id == merchant_id))

    def aggregates(
        self,
        merchant_id: UUID,
        now: datetime,
        payment_days: int,
        fulfillment_days: int,
        dispute_days: int,
    ) -> dict[str, Any]:
        """Every count the signals need, in one row"""
        payments_from: datetime = now - timedelta(days=payment_days)
        orders_from: datetime = now - timedelta(days=fulfillment_days)
        disputes_from: datetime = now - timedelta(days=dispute_days)

        def count(*conditions) -> Any:
            return (
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.merchant_id == merchant_id,
                    Transaction.status == TransactionStatus.SUCCESS,
                    *conditions,
                )
                .scalar_subquery()
            )

        # an order counts as fulfilled with a fulfillment carrying at least one evidence
        # item: a photo, a tracking number or a confirmation (who received it)
        proof = exists().where(
            Fulfillment.order_id == Order.id,
            or_(
                _filled(Fulfillment.tracking_number),
                _filled(Fulfillment.recipient_name),
                exists().where(StoredFile.fulfillment_id == Fulfillment.id),
            ),
        )
        orders = (
            select(func.count().label("completed"), func.count().filter(proof).label("fulfilled"))
            .where(
                Order.merchant_id == merchant_id,
                Order.status.in_(COMPLETED_ORDERS),
                Order.ordered_at >= orders_from,
            )
            .subquery("orders")
        )

        responded = Dispute.submitted_at.is_not(None)
        window = func.extract("epoch", Dispute.due_at - Dispute.created_at)
        used = func.extract("epoch", Dispute.submitted_at - Dispute.created_at)
        disputes = (
            select(
                func.count().label("total"),
                func.count().filter(Dispute.status.in_(RESOLVED)).label("resolved"),
                func.count().filter(Dispute.status == DisputeStatus.WON).label("won"),
                # share of each dispute's own window used, capped at all of it
                func.avg(
                    case(
                        (window > 0, func.least(func.greatest(used / window, 0), 1) * 100),
                        else_=literal(None),
                    )
                )
                .filter(responded)
                .label("response_pct"),
            )
            .where(Dispute.merchant_id == merchant_id, Dispute.created_at >= disputes_from)
            .subquery("disputes")
        )

        row = self._session.execute(
            select(
                count(Transaction.paid_at >= payments_from).label("payments"),
                count(
                    Transaction.paid_at >= payments_from,
                    Transaction.order_id.is_not(None),
                    Transaction.reconciliation_status.in_(MATCHED),
                ).label("matched"),
                count(Transaction.paid_at >= disputes_from).label("payments_dispute_window"),
                *orders.c,
                disputes.c.total,
                disputes.c.resolved,
                disputes.c.won,
                disputes.c.response_pct,
            ).select_from(orders.join(disputes, literal(True)))
        ).one()

        return {
            "payments": row.payments,
            "matched": row.matched,
            "payments_dispute_window": row.payments_dispute_window,
            "completed_orders": row.completed,
            "fulfilled_orders": row.fulfilled,
            "disputes": row.total,
            "resolved_disputes": row.resolved,
            "won_disputes": row.won,
            "response_pct": float(row.response_pct) if row.response_pct is not None else None,
        }

    def readiness_facts(
        self, merchant_id: UUID, since: datetime, repeat_payments: int
    ) -> dict[UUID, tuple[bool, ...]]:
        """Readiness facts of the matched payments paid since since, in one query"""
        matched = select(Transaction.id).where(
            Transaction.merchant_id == merchant_id,
            Transaction.status == TransactionStatus.SUCCESS,
            Transaction.paid_at >= since,
            Transaction.order_id.is_not(None),
            Transaction.reconciliation_status.in_(MATCHED),
        )
        rows = self._session.execute(
            ReadinessRepository.evidence_statement(matched, repeat_payments)
        ).all()
        return ReadinessRepository.to_facts(rows)

    def profile_for_update(self, merchant_id: UUID) -> TrustProfile:
        """The merchant's profile, created on first use, locked"""
        self._session.execute(
            insert(TrustProfile)
            .values(
                merchant_id=merchant_id,
                current_state=TrustState.NEW,
                public_token=new_public_token(),
            )
            .on_conflict_do_nothing(index_elements=["merchant_id"])
        )
        return self._session.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant_id).with_for_update()
        )

    def add_snapshot(self, snapshot: TrustSnapshot) -> TrustSnapshot:
        self._session.add(snapshot)
        return snapshot

    def recent_snapshots(self, merchant_id: UUID, limit: int = 5) -> list[TrustSnapshot]:
        """Return bounded prior trust snapshots for the AI's merchant memory."""
        return list(
            self._session.scalars(
                select(TrustSnapshot)
                .where(TrustSnapshot.merchant_id == merchant_id)
                .order_by(TrustSnapshot.created_at.desc(), TrustSnapshot.id.desc())
                .limit(limit)
            )
        )

    def all_snapshots(self, merchant_id: UUID) -> list[TrustSnapshot]:
        """Return the complete durable trust history for memory indexing."""
        return list(
            self._session.scalars(
                select(TrustSnapshot)
                .where(TrustSnapshot.merchant_id == merchant_id)
                .order_by(TrustSnapshot.created_at.asc(), TrustSnapshot.id.asc())
            )
        )

    def active_merchants(self) -> list[UUID]:
        """Merchants the daily run recomputes"""
        return list(
            self._session.scalars(
                select(Merchant.id).where(
                    Merchant.is_active.is_(True), Merchant.is_verified.is_(True)
                )
            )
        )


class TrustRepository(BaseRepository[BaseModel, TrustProfile]):
    model = TrustProfile

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return TrustProfile(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        return filter_conditions

    async def ensure_profile(self, merchant_id: UUID) -> TrustProfile:
        """The profile, created (state new) when the merchant has none yet"""
        await self._async_session.execute(
            insert(TrustProfile)
            .values(
                merchant_id=merchant_id,
                current_state=TrustState.NEW,
                public_token=new_public_token(),
            )
            .on_conflict_do_nothing(index_elements=["merchant_id"])
        )
        return await self.get_record(merchant_id=merchant_id)

    @staticmethod
    def _stable_since(merchant_id_column, state_column) -> Any:
        """When the current state began: the first snapshot in it after the last snapshot
        in any other state"""
        later = aliased(TrustSnapshot)
        other = aliased(TrustSnapshot)
        last_other = (
            select(func.max(other.created_at))
            .where(other.merchant_id == merchant_id_column, other.state != state_column)
            .scalar_subquery()
        )
        return (
            select(func.min(later.created_at))
            .where(
                later.merchant_id == merchant_id_column,
                later.state == state_column,
                or_(last_other.is_(None), later.created_at > last_other),
            )
            .scalar_subquery()
        )

    async def profile_with_settings(
        self, merchant_id: UUID
    ) -> tuple[TrustProfile, bool, bool, datetime | None] | None:
        """The profile, the public and widget switches and when the state began"""
        row = (
            await self._async_session.execute(
                select(
                    TrustProfile,
                    func.coalesce(MerchantSettings.trust_public_enabled, False),
                    func.coalesce(MerchantSettings.trust_widget_enabled, False),
                    self._stable_since(TrustProfile.merchant_id, TrustProfile.current_state),
                )
                .outerjoin(
                    MerchantSettings, MerchantSettings.merchant_id == TrustProfile.merchant_id
                )
                .where(TrustProfile.merchant_id == merchant_id)
            )
        ).one_or_none()
        return (row[0], row[1], row[2], row[3]) if row else None

    async def public_profile(self, token: str) -> Any | None:
        """Only what a public page needs: name, state, when it was computed and began, the
        switches, the month's payment count and the two rates the summary is worded from.
        Never the score, the other rates or any id"""
        row = (
            await self._async_session.execute(
                select(
                    Merchant.business_name,
                    TrustProfile.current_state,
                    TrustProfile.last_computed_at,
                    # the two signals the public summary is worded from
                    TrustProfile.reconciliation_rate,
                    TrustProfile.fulfillment_rate,
                    TrustProfile.payments_30d,
                    MerchantSettings.trust_public_enabled,
                    MerchantSettings.trust_widget_enabled,
                    self._stable_since(TrustProfile.merchant_id, TrustProfile.current_state).label(
                        "stable_since"
                    ),
                )
                .join(Merchant, Merchant.id == TrustProfile.merchant_id)
                .join(MerchantSettings, MerchantSettings.merchant_id == TrustProfile.merchant_id)
                .where(TrustProfile.public_token == token, Merchant.is_active.is_(True))
            )
        ).one_or_none()
        return row

    async def snapshots(self, merchant_id: UUID, since: datetime) -> list[TrustSnapshot]:
        return list(
            await self._async_session.scalars(
                select(TrustSnapshot)
                .where(TrustSnapshot.merchant_id == merchant_id, TrustSnapshot.created_at >= since)
                .order_by(TrustSnapshot.created_at, TrustSnapshot.id)
            )
        )

    async def settings_for_update(self, merchant_id: UUID) -> MerchantSettings | None:
        return await self._async_session.scalar(
            select(MerchantSettings)
            .where(MerchantSettings.merchant_id == merchant_id)
            .with_for_update()
        )

    async def profile_for_update(self, merchant_id: UUID) -> TrustProfile | None:
        return await self.get_record(for_update=True, merchant_id=merchant_id)

    async def snapshot_for_update(self, snapshot_id: UUID) -> TrustSnapshot | None:
        return await self._async_session.get(TrustSnapshot, snapshot_id, with_for_update=True)
