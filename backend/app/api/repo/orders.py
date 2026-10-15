from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select

from app.api.models.customers import Customer
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import LIKE_ESCAPE, BaseRepository, contains_pattern
from app.api.schemas.orders import OrderInDB, OrderListQuery


class OrderRepository(BaseRepository[OrderInDB, Order]):
    model = Order

    @staticmethod
    def _entity_to_model(entity: OrderInDB) -> model:
        return Order(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "customer_id" in filters:
            filter_conditions.append(self.model.customer_id == filters["customer_id"])

        return filter_conditions

    def _is_linked(self):
        return exists().where(Transaction.order_id == self.model.id).label("is_linked")

    async def is_linked(self, order_id: UUID) -> bool:
        """Linked to a synced payment by reconciliation"""
        return await self._async_session.scalar(
            select(exists().where(Transaction.order_id == order_id))
        )

    async def list_orders(
        self,
        merchant_id: UUID,
        query: OrderListQuery,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[list[tuple[Order, Customer | None, bool]], int]:
        """Page of orders with their customer and link state, and the total matching the
        filters. created_from / created_before are the date filters already in UTC"""
        conditions: list[Any] = [self.model.merchant_id == merchant_id]

        if query.status:
            conditions.append(self.model.status.in_(query.status))
        if query.customer_id:
            conditions.append(self.model.customer_id == query.customer_id)
        if created_from:
            conditions.append(self.model.created_at >= created_from)
        if created_before:
            conditions.append(self.model.created_at < created_before)
        if query.search:
            pattern: str = contains_pattern(query.search)
            conditions.append(
                or_(
                    self.model.order_number.ilike(pattern, escape=LIKE_ESCAPE),
                    self.model.description.ilike(pattern, escape=LIKE_ESCAPE),
                    Customer.name.ilike(pattern, escape=LIKE_ESCAPE),
                    Customer.email.ilike(pattern, escape=LIKE_ESCAPE),
                )
            )

        total: int = await self._async_session.scalar(
            select(func.count(self.model.id))
            .outerjoin(Customer, Customer.id == self.model.customer_id)
            .where(*conditions)
        )

        sort_columns: dict[str, Any] = {
            "created_at": self.model.created_at,
            "amount": self.model.amount,
            "order_number": func.lower(self.model.order_number),
        }
        descending: bool = query.sort.startswith("-")
        sort_column = sort_columns.get(query.sort.lstrip("-"), self.model.created_at)

        # id breaks ties so pages never repeat or skip rows
        order_by = (
            (sort_column.desc().nulls_last(), self.model.id.desc())
            if descending
            else (sort_column.asc().nulls_last(), self.model.id.asc())
        )

        stmt: Select = (
            select(self.model, Customer, self._is_linked())
            .outerjoin(Customer, Customer.id == self.model.customer_id)
            .where(*conditions)
            .order_by(*order_by)
            .offset(query.offset)
            .limit(query.limit)
        )

        rows = (await self._async_session.execute(stmt)).all()

        return [(row[0], row[1], row[2]) for row in rows], total
