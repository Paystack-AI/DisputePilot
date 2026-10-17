from datetime import date, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.fulfillments import Fulfillment
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository
from app.api.repo.orders import OrderRepository
from app.api.schemas.pagination import PageParams
from app.api.schemas.transactions import TransactionListQuery


class TransactionRepository(BaseRepository[BaseModel, Transaction]):
    """Read side only for now; transactions are written by the paystack sync"""

    model = Transaction

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return Transaction(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "customer_id" in filters:
            filter_conditions.append(self.model.customer_id == filters["customer_id"])
        if "order_id" in filters:
            filter_conditions.append(self.model.order_id == filters["order_id"])

        return filter_conditions

    async def list_for_customer(
        self, merchant_id: UUID, customer_id: UUID, params: PageParams
    ) -> tuple[list[Transaction], int]:
        conditions: list[Any] = [
            self.model.merchant_id == merchant_id,
            self.model.customer_id == customer_id,
        ]

        rows, total = await self._paginate(
            select(self.model)
            .where(*conditions)
            # newest payment first; id breaks ties so pages never repeat or skip rows
            .order_by(self.model.paid_at.desc().nulls_last(), self.model.id.desc()),
            select(func.count(self.model.id)).where(*conditions),
            params.page,
            params.limit,
        )

        return [row[0] for row in rows], total

    async def list_for_order(self, merchant_id: UUID, order_id: UUID) -> list[Transaction]:
        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.merchant_id == merchant_id, self.model.order_id == order_id)
            .order_by(self.model.paid_at.desc().nulls_last(), self.model.id.desc())
        )

        return list(rows)

    def _with_links(self) -> Select:
        """The payment, its customer and its linked order. The customer is the one set at
        sync, or else the linked order's"""
        return (
            select(self.model, Customer, Order)
            .outerjoin(Order, Order.id == self.model.order_id)
            .outerjoin(
                Customer, Customer.id == func.coalesce(self.model.customer_id, Order.customer_id)
            )
        )

    async def list_transactions(
        self, merchant_id: UUID, query: TransactionListQuery
    ) -> tuple[list[tuple[Transaction, Customer | None, Order | None]], int]:
        """Page of payments and the total matching the filters. Dates are days in the
        merchant's timezone on paystack_created_at, so unpaid attempts are included (filter
        status for paid only); date_to includes the whole day"""
        conditions: list[Any] = [self.model.merchant_id == merchant_id]

        if query.status:
            conditions.append(self.model.status.in_(query.status))
        if query.reconciliation_status:
            conditions.append(self.model.reconciliation_status.in_(query.reconciliation_status))
        if query.customer_id:
            conditions.append(self.model.customer_id == query.customer_id)
        if query.date_from:
            conditions.append(
                self.model.paystack_created_at
                >= OrderRepository._merchant_day_start(merchant_id, query.date_from)
            )
        if query.date_to:
            next_day: date = query.date_to + timedelta(days=1)
            conditions.append(
                self.model.paystack_created_at
                < OrderRepository._merchant_day_start(merchant_id, next_day)
            )

        sort_columns: dict[str, Any] = {
            "created_at": self.model.paystack_created_at,
            "paid_at": self.model.paid_at,
            "amount": self.model.amount,
        }
        sort_column = sort_columns[query.sort.lstrip("-")]
        # id breaks ties so pages never repeat or skip rows
        order_by = (
            (sort_column.desc().nulls_last(), self.model.id.desc())
            if query.sort.startswith("-")
            else (sort_column.asc().nulls_last(), self.model.id.asc())
        )

        rows, total = await self._paginate(
            self._with_links().where(*conditions).order_by(*order_by),
            select(func.count(self.model.id)).where(*conditions),
            query.page,
            query.limit,
        )

        return [(row[0], row[1], row[2]) for row in rows], total

    async def get_by_reference(
        self, merchant_id: UUID, reference: str, for_update: bool = False
    ) -> tuple[Transaction, Customer | None, Order | None] | None:
        """for_update locks only the transaction row"""
        stmt: Select = self._with_links().where(
            self.model.merchant_id == merchant_id, self.model.paystack_reference == reference
        )
        if for_update:
            stmt = stmt.with_for_update(of=self.model)

        row = (await self._async_session.execute(stmt)).one_or_none()
        if row is None:
            return None

        return row[0], row[1], row[2]

    async def list_fulfillments(self, transaction: Transaction) -> list[Fulfillment]:
        """Fulfillments recorded against the payment or against its linked order"""
        linked = [Fulfillment.transaction_id == transaction.id]
        if transaction.order_id:
            linked.append(Fulfillment.order_id == transaction.order_id)

        rows = await self._async_session.scalars(
            select(Fulfillment)
            .where(Fulfillment.merchant_id == transaction.merchant_id, or_(*linked))
            .order_by(Fulfillment.delivery_date.desc(), Fulfillment.id.desc())
        )
        return list(rows)

    async def latest_dispute(self, transaction: Transaction) -> Dispute | None:
        return await self._async_session.scalar(
            select(Dispute)
            .where(
                Dispute.merchant_id == transaction.merchant_id,
                Dispute.transaction_id == transaction.id,
            )
            .order_by(Dispute.created_at.desc())
            .limit(1)
        )
