"""Queries behind reconciliation matching. MatchingRepository runs them on the api's async
session, SyncMatchingRepository on a celery task's sync session; both build the same
statements, so the two modes read and write alike.

A transaction-scoped advisory lock per merchant keeps two passes (a sync finishing while
the merchant starts a session) from linking the same order twice.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Executable, Row, delete, exists, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.api.models.customers import Customer
from app.api.models.enums import (
    MatchSuggestionStatus,
    OrderStatus,
    ReconciliationStatus,
    TransactionStatus,
)
from app.api.models.match_suggestions import MatchSuggestion
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository

_LinkedPayment = aliased(Transaction)


def open_order_conditions() -> list[Any]:
    """An order a payment can still be matched to"""
    return [
        Order.status == OrderStatus.PENDING,
        Order.resolution.is_(None),
        Order.flagged_at.is_(None),
        # aliased: also used in queries that already select transactions
        ~exists().where(_LinkedPayment.order_id == Order.id),
    ]


def open_payment_conditions() -> list[Any]:
    """A paid payment not linked, suggested away or flagged yet"""
    return [
        Transaction.status == TransactionStatus.SUCCESS,
        Transaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
        Transaction.order_id.is_(None),
    ]


class _Statements:
    """Statement builders shared by the async and sync repositories"""

    @staticmethod
    def lock(merchant_id: UUID) -> Executable:
        return select(
            func.pg_advisory_xact_lock(func.hashtextextended(f"reconcile:{merchant_id}", 0))
        )

    @staticmethod
    def open_payments(merchant_id: UUID, paid_from: datetime, paid_to: datetime) -> Executable:
        """id, reference, amount, currency, paid_at, metadata, customer_id, customer shared"""
        return (
            select(
                Transaction.id,
                Transaction.paystack_reference,
                Transaction.amount,
                Transaction.currency,
                Transaction.paid_at,
                Transaction.metadata_,
                Transaction.customer_id,
                func.coalesce(Customer.is_shared, false()),
            )
            .outerjoin(Customer, Customer.id == Transaction.customer_id)
            .where(
                Transaction.merchant_id == merchant_id,
                *open_payment_conditions(),
                Transaction.paid_at >= paid_from,
                Transaction.paid_at < paid_to,
            )
        )

    @staticmethod
    def open_orders(merchant_id: UUID, created_from: datetime, created_to: datetime) -> Executable:
        """id, order_number, amount, currency, customer_id, ordered_at"""
        return select(
            Order.id,
            Order.order_number,
            Order.amount,
            Order.currency,
            Order.customer_id,
            Order.ordered_at,
        ).where(
            Order.merchant_id == merchant_id,
            *open_order_conditions(),
            Order.ordered_at >= created_from,
            Order.ordered_at <= created_to,
        )

    @staticmethod
    def rejected_pairs(merchant_id: UUID, transaction_ids: list[UUID]) -> Executable:
        return select(MatchSuggestion.transaction_id, MatchSuggestion.order_id).where(
            MatchSuggestion.merchant_id == merchant_id,
            MatchSuggestion.status == MatchSuggestionStatus.REJECTED,
            MatchSuggestion.transaction_id.in_(transaction_ids),
        )

    @staticmethod
    def tier1_auto(merchant_id: UUID) -> Executable:
        return select(MerchantSettings.auto_reconciliation_tier1).where(
            MerchantSettings.merchant_id == merchant_id
        )

    @staticmethod
    def link(
        transaction_id: UUID, order_id: UUID, tier: int, confidence: int, now: datetime
    ) -> list[Executable]:
        """Link an open payment to the order (auto_matched); the order becomes paid"""
        return [
            update(Transaction)
            .where(Transaction.id == transaction_id, *open_payment_conditions())
            .values(
                order_id=order_id,
                reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
                reconciled_at=now,
                match_tier=tier,
                match_confidence=confidence,
                # the order's customer when paystack sent none
                customer_id=func.coalesce(
                    Transaction.customer_id,
                    select(Order.customer_id).where(Order.id == order_id).scalar_subquery(),
                ),
            ),
            update(Order)
            .where(Order.id == order_id, Order.status == OrderStatus.PENDING)
            .values(status=OrderStatus.PAID, updated_at=now),
        ]

    @staticmethod
    def flag(transaction_id: UUID, reason: str, now: datetime) -> Executable:
        return (
            update(Transaction)
            .where(Transaction.id == transaction_id, *open_payment_conditions())
            .values(
                reconciliation_status=ReconciliationStatus.FLAGGED,
                flag_reason=reason,
                flagged_at=now,
            )
        )

    @staticmethod
    def clear_pending(merchant_id: UUID, transaction_ids: list[UUID]) -> Executable:
        return delete(MatchSuggestion).where(
            MatchSuggestion.merchant_id == merchant_id,
            MatchSuggestion.status == MatchSuggestionStatus.PENDING,
            MatchSuggestion.transaction_id.in_(transaction_ids),
        )

    @staticmethod
    def add_suggestions(rows: list[dict]) -> Executable:
        # a rejected pair keeps its row
        return (
            insert(MatchSuggestion)
            .values(rows)
            .on_conflict_do_nothing(constraint="match_suggestions_pair_uq")
        )

    @staticmethod
    def drop_stale(merchant_id: UUID) -> Executable:
        """Pending suggestions whose payment or order was settled some other way"""
        return delete(MatchSuggestion).where(
            MatchSuggestion.merchant_id == merchant_id,
            MatchSuggestion.status == MatchSuggestionStatus.PENDING,
            or_(
                MatchSuggestion.transaction_id.in_(
                    select(Transaction.id).where(
                        Transaction.merchant_id == merchant_id,
                        or_(
                            Transaction.order_id.is_not(None),
                            Transaction.reconciliation_status != ReconciliationStatus.UNMATCHED,
                        ),
                    )
                ),
                MatchSuggestion.order_id.not_in(
                    select(Order.id).where(
                        Order.merchant_id == merchant_id, *open_order_conditions()
                    )
                ),
            ),
        )


class MatchingRepository(BaseRepository[BaseModel, MatchSuggestion]):
    model = MatchSuggestion

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return MatchSuggestion(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        return []

    async def lock(self, merchant_id: UUID):
        """Held until the transaction ends"""
        await self._async_session.execute(_Statements.lock(merchant_id))

    async def open_payments(
        self, merchant_id: UUID, paid_from: datetime, paid_to: datetime
    ) -> list[Row]:
        return list(
            await self._async_session.execute(
                _Statements.open_payments(merchant_id, paid_from, paid_to)
            )
        )

    async def open_orders(
        self, merchant_id: UUID, created_from: datetime, created_to: datetime
    ) -> list[Row]:
        return list(
            await self._async_session.execute(
                _Statements.open_orders(merchant_id, created_from, created_to)
            )
        )

    async def rejected_pairs(
        self, merchant_id: UUID, transaction_ids: list[UUID]
    ) -> set[tuple[UUID, UUID]]:
        rows = await self._async_session.execute(
            _Statements.rejected_pairs(merchant_id, transaction_ids)
        )
        return {(row[0], row[1]) for row in rows}

    async def tier1_auto(self, merchant_id: UUID) -> bool:
        return await self._async_session.scalar(_Statements.tier1_auto(merchant_id)) is not False

    async def link(
        self, transaction_id: UUID, order_id: UUID, tier: int, confidence: int, now: datetime
    ):
        for statement in _Statements.link(transaction_id, order_id, tier, confidence, now):
            await self._async_session.execute(statement)

    async def flag(self, transaction_id: UUID, reason: str, now: datetime):
        await self._async_session.execute(_Statements.flag(transaction_id, reason, now))

    async def replace_suggestions(
        self, merchant_id: UUID, transaction_ids: list[UUID], rows: list[dict]
    ):
        """The pass recomputes every suggestion for the payments it looked at"""
        await self._async_session.execute(_Statements.clear_pending(merchant_id, transaction_ids))
        if rows:
            await self._async_session.execute(_Statements.add_suggestions(rows))

    async def drop_stale_suggestions(self, merchant_id: UUID):
        await self._async_session.execute(_Statements.drop_stale(merchant_id))

    async def order_is_open(self, order_id: UUID) -> bool:
        """Whether a payment can still be matched to the order"""
        return bool(
            await self._async_session.scalar(
                select(exists().where(Order.id == order_id, *open_order_conditions()))
            )
        )

    async def get_suggestion(
        self, merchant_id: UUID, transaction_id: UUID, order_id: UUID, for_update: bool = False
    ) -> MatchSuggestion | None:
        stmt = select(MatchSuggestion).where(
            MatchSuggestion.merchant_id == merchant_id,
            MatchSuggestion.transaction_id == transaction_id,
            MatchSuggestion.order_id == order_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self._async_session.scalar(stmt)

    async def drop_pending_for(self, transaction_id: UUID, order_id: UUID):
        """Every other suggestion for the payment or the order, once they are matched"""
        await self._async_session.execute(
            delete(MatchSuggestion).where(
                MatchSuggestion.status == MatchSuggestionStatus.PENDING,
                or_(
                    MatchSuggestion.transaction_id == transaction_id,
                    MatchSuggestion.order_id == order_id,
                ),
            )
        )

    async def reject_pair(
        self, merchant_id: UUID, transaction_id: UUID, order_id: UUID, tier: int, now: datetime
    ):
        """Record the pair as rejected so it is never matched or suggested again"""
        await self._async_session.execute(
            insert(MatchSuggestion)
            .values(
                merchant_id=merchant_id,
                transaction_id=transaction_id,
                order_id=order_id,
                tier=tier,
                confidence=0,
                reason="Automatic match rejected by the merchant.",
                status=MatchSuggestionStatus.REJECTED,
                rejected_at=now,
                created_at=now,
            )
            .on_conflict_do_update(
                constraint="match_suggestions_pair_uq",
                set_={"status": MatchSuggestionStatus.REJECTED, "rejected_at": now},
            )
        )


class SyncMatchingRepository:
    """MatchingRepository's matching queries on a sync session, for celery"""

    def __init__(self, session: Session):
        self._session = session

    def lock(self, merchant_id: UUID):
        self._session.execute(_Statements.lock(merchant_id))

    def open_payments(self, merchant_id: UUID, paid_from: datetime, paid_to: datetime) -> list[Row]:
        return list(
            self._session.execute(_Statements.open_payments(merchant_id, paid_from, paid_to))
        )

    def open_orders(
        self, merchant_id: UUID, created_from: datetime, created_to: datetime
    ) -> list[Row]:
        return list(
            self._session.execute(_Statements.open_orders(merchant_id, created_from, created_to))
        )

    def rejected_pairs(
        self, merchant_id: UUID, transaction_ids: list[UUID]
    ) -> set[tuple[UUID, UUID]]:
        rows = self._session.execute(_Statements.rejected_pairs(merchant_id, transaction_ids))
        return {(row[0], row[1]) for row in rows}

    def tier1_auto(self, merchant_id: UUID) -> bool:
        return self._session.scalar(_Statements.tier1_auto(merchant_id)) is not False

    def link(self, transaction_id: UUID, order_id: UUID, tier: int, confidence: int, now: datetime):
        for statement in _Statements.link(transaction_id, order_id, tier, confidence, now):
            self._session.execute(statement)

    def flag(self, transaction_id: UUID, reason: str, now: datetime):
        self._session.execute(_Statements.flag(transaction_id, reason, now))

    def replace_suggestions(self, merchant_id: UUID, transaction_ids: list[UUID], rows: list[dict]):
        self._session.execute(_Statements.clear_pending(merchant_id, transaction_ids))
        if rows:
            self._session.execute(_Statements.add_suggestions(rows))

    def drop_stale_suggestions(self, merchant_id: UUID):
        self._session.execute(_Statements.drop_stale(merchant_id))
