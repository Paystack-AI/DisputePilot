from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.models.customers import Customer
from app.api.models.enums import (
    MatchSuggestionStatus,
    ReconciliationSessionStatus,
    ReconciliationStatus,
    TransactionStatus,
)
from app.api.models.match_suggestions import MatchSuggestion
from app.api.models.orders import Order
from app.api.models.reconciliation_sessions import ReconciliationSession
from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository
from app.api.repo.matching import open_order_conditions
from app.api.schemas.pagination import PageParams

# items per category in a session view; the totals carry the full counts
LIST_LIMIT: int = 200

OrderCustomer = aliased(Customer)


def _has_pending_suggestion():
    return exists().where(
        MatchSuggestion.transaction_id == Transaction.id,
        MatchSuggestion.status == MatchSuggestionStatus.PENDING,
    )


def _order_has_pending_suggestion():
    return exists().where(
        MatchSuggestion.order_id == Order.id,
        MatchSuggestion.status == MatchSuggestionStatus.PENDING,
    )


def _order_is_linked():
    return exists().where(Transaction.order_id == Order.id).label("is_linked")


class ReconciliationRepository(BaseRepository[BaseModel, ReconciliationSession]):
    model = ReconciliationSession

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return ReconciliationSession(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "status" in filters:
            filter_conditions.append(self.model.status == filters["status"])

        return filter_conditions

    # ------------------------------ sessions ------------------------------ #

    async def get_open(
        self, merchant_id: UUID, for_update: bool = False
    ) -> ReconciliationSession | None:
        return await self.get_record(
            for_update=for_update,
            merchant_id=merchant_id,
            status=ReconciliationSessionStatus.IN_PROGRESS,
        )

    async def latest(self, merchant_id: UUID) -> ReconciliationSession | None:
        return await self._async_session.scalar(
            select(self.model)
            .where(self.model.merchant_id == merchant_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(1)
        )

    async def list_sessions(
        self, merchant_id: UUID, params: PageParams
    ) -> tuple[list[ReconciliationSession], int]:
        rows, total = await self._paginate(
            select(self.model)
            .where(self.model.merchant_id == merchant_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc()),
            select(func.count(self.model.id)).where(self.model.merchant_id == merchant_id),
            params.page,
            params.limit,
        )
        return [row[0] for row in rows], total

    async def last_completed_at(self, merchant_id: UUID) -> datetime | None:
        return await self._async_session.scalar(
            select(func.max(self.model.completed_at)).where(
                self.model.merchant_id == merchant_id,
                self.model.status == ReconciliationSessionStatus.COMPLETED,
            )
        )

    # ------------------------------ categories ------------------------------ #

    @staticmethod
    def _paid_in(merchant_id: UUID, paid_from: datetime, paid_to: datetime) -> list[Any]:
        return [
            Transaction.merchant_id == merchant_id,
            Transaction.status == TransactionStatus.SUCCESS,
            Transaction.paid_at >= paid_from,
            Transaction.paid_at < paid_to,
        ]

    @staticmethod
    def _orders_in(merchant_id: UUID, created_from: datetime, created_to: datetime) -> list[Any]:
        return [
            Order.merchant_id == merchant_id,
            Order.created_at >= created_from,
            Order.created_at < created_to,
        ]

    def _payments_with_links(self) -> Select:
        """The payment, its customer (from sync, else the order's) and its order"""
        return (
            select(Transaction, Customer, Order)
            .outerjoin(Order, Order.id == Transaction.order_id)
            .outerjoin(
                Customer, Customer.id == func.coalesce(Transaction.customer_id, Order.customer_id)
            )
        )

    @staticmethod
    def _newest_payments_first() -> tuple:
        return Transaction.paid_at.desc(), Transaction.id.desc()

    async def totals(
        self,
        merchant_id: UUID,
        paid_from: datetime,
        paid_to: datetime,
    ) -> dict[str, int]:
        """Counts for every category, in two queries"""
        flagged = Transaction.reconciliation_status == ReconciliationStatus.FLAGGED
        unmatched = (Transaction.reconciliation_status == ReconciliationStatus.UNMATCHED) & (
            Transaction.order_id.is_(None)
        )

        row = (
            await self._async_session.execute(
                select(
                    func.count(),
                    func.count().filter(~flagged & Transaction.order_id.is_not(None)),
                    func.count().filter(unmatched & _has_pending_suggestion()),
                    func.count().filter(unmatched & ~_has_pending_suggestion()),
                    func.count().filter(flagged),
                ).where(*self._paid_in(merchant_id, paid_from, paid_to))
            )
        ).one()

        unmatched_orders: int = await self._async_session.scalar(
            select(func.count(Order.id)).where(
                *self._orders_in(merchant_id, paid_from, paid_to),
                *open_order_conditions(),
                ~_order_has_pending_suggestion(),
            )
        )

        return {
            "total_transactions": row[0],
            "matched": row[1],
            "suggested": row[2],
            "unmatched_payments": row[3],
            "flagged": row[4],
            "unmatched_orders": unmatched_orders,
        }

    async def matched(
        self, merchant_id: UUID, paid_from: datetime, paid_to: datetime
    ) -> list[tuple[Transaction, Customer | None, Order, Customer | None]]:
        rows = await self._async_session.execute(
            select(Transaction, Customer, Order, OrderCustomer)
            .join(Order, Order.id == Transaction.order_id)
            .outerjoin(
                Customer, Customer.id == func.coalesce(Transaction.customer_id, Order.customer_id)
            )
            .outerjoin(OrderCustomer, OrderCustomer.id == Order.customer_id)
            .where(
                *self._paid_in(merchant_id, paid_from, paid_to),
                Transaction.reconciliation_status != ReconciliationStatus.FLAGGED,
            )
            .order_by(*self._newest_payments_first())
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    async def suggestions(
        self, merchant_id: UUID, paid_from: datetime, paid_to: datetime
    ) -> list[tuple[MatchSuggestion, Transaction, Customer | None, Order, Customer | None]]:
        rows = await self._async_session.execute(
            select(MatchSuggestion, Transaction, Customer, Order, OrderCustomer)
            .join(Transaction, Transaction.id == MatchSuggestion.transaction_id)
            .join(Order, Order.id == MatchSuggestion.order_id)
            .outerjoin(Customer, Customer.id == Transaction.customer_id)
            .outerjoin(OrderCustomer, OrderCustomer.id == Order.customer_id)
            .where(
                MatchSuggestion.merchant_id == merchant_id,
                MatchSuggestion.status == MatchSuggestionStatus.PENDING,
                *self._paid_in(merchant_id, paid_from, paid_to),
                Transaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
                Transaction.order_id.is_(None),
                *open_order_conditions(),
            )
            .order_by(
                *self._newest_payments_first(),
                MatchSuggestion.confidence.desc(),
                MatchSuggestion.id,
            )
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    async def unmatched_payments(
        self, merchant_id: UUID, paid_from: datetime, paid_to: datetime
    ) -> list[tuple[Transaction, Customer | None, Order | None]]:
        rows = await self._async_session.execute(
            self._payments_with_links()
            .where(
                *self._paid_in(merchant_id, paid_from, paid_to),
                Transaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
                Transaction.order_id.is_(None),
                ~_has_pending_suggestion(),
            )
            .order_by(*self._newest_payments_first())
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    async def flagged(
        self, merchant_id: UUID, paid_from: datetime, paid_to: datetime
    ) -> list[tuple[Transaction, Customer | None, Order | None]]:
        rows = await self._async_session.execute(
            self._payments_with_links()
            .where(
                *self._paid_in(merchant_id, paid_from, paid_to),
                Transaction.reconciliation_status == ReconciliationStatus.FLAGGED,
            )
            .order_by(*self._newest_payments_first())
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    def _orders_with_customer(self) -> Select:
        return select(Order, Customer, _order_is_linked()).outerjoin(
            Customer, Customer.id == Order.customer_id
        )

    async def unmatched_orders(
        self, merchant_id: UUID, created_from: datetime, created_to: datetime
    ) -> list[tuple[Order, Customer | None, bool]]:
        rows = await self._async_session.execute(
            self._orders_with_customer()
            .where(
                *self._orders_in(merchant_id, created_from, created_to),
                *open_order_conditions(),
                ~_order_has_pending_suggestion(),
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    async def flagged_orders(
        self, merchant_id: UUID, created_from: datetime, created_to: datetime
    ) -> list[tuple[Order, Customer | None, bool]]:
        rows = await self._async_session.execute(
            self._orders_with_customer()
            .where(
                *self._orders_in(merchant_id, created_from, created_to),
                Order.flagged_at.is_not(None),
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(LIST_LIMIT)
        )
        return [tuple(row) for row in rows.all()]

    # ------------------------------ decisions ------------------------------ #

    async def get_transaction(
        self, merchant_id: UUID, transaction_id: UUID, for_update: bool = False
    ) -> tuple[Transaction, Customer | None, Order | None] | None:
        stmt = self._payments_with_links().where(
            Transaction.merchant_id == merchant_id, Transaction.id == transaction_id
        )
        if for_update:
            stmt = stmt.with_for_update(of=Transaction)
        row = (await self._async_session.execute(stmt)).one_or_none()
        return tuple(row) if row else None

    async def get_order(
        self, merchant_id: UUID, order_id: UUID, for_update: bool = False
    ) -> tuple[Order, Customer | None, bool] | None:
        stmt = self._orders_with_customer().where(
            Order.merchant_id == merchant_id, Order.id == order_id
        )
        if for_update:
            stmt = stmt.with_for_update(of=Order)
        row = (await self._async_session.execute(stmt)).one_or_none()
        return tuple(row) if row else None

    async def summary_counts(
        self, merchant_id: UUID, today_start: datetime, review_from: datetime
    ) -> tuple[int, int, int]:
        """Synced today, matched today, needing review in the last 30 days"""
        needs_review = Transaction.reconciliation_status.in_(
            [ReconciliationStatus.UNMATCHED, ReconciliationStatus.FLAGGED]
        ) & or_(
            Transaction.order_id.is_(None),
            Transaction.reconciliation_status == ReconciliationStatus.FLAGGED,
        )
        row = (
            await self._async_session.execute(
                select(
                    func.count().filter(Transaction.synced_at >= today_start),
                    func.count().filter(
                        Transaction.order_id.is_not(None), Transaction.reconciled_at >= today_start
                    ),
                    func.count().filter(
                        needs_review,
                        Transaction.status == TransactionStatus.SUCCESS,
                        Transaction.paid_at >= review_from,
                    ),
                ).where(Transaction.merchant_id == merchant_id)
            )
        ).one()
        return row[0], row[1], row[2]
