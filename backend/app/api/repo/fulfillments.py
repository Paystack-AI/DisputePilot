from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select

from app.api.models.fulfillments import Fulfillment
from app.api.repo.base import BaseRepository
from app.api.schemas.fulfillments import FulfillmentInDB, FulfillmentListQuery


class FulfillmentRepository(BaseRepository[FulfillmentInDB, Fulfillment]):
    model = Fulfillment

    @staticmethod
    def _entity_to_model(entity: FulfillmentInDB) -> model:
        return Fulfillment(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "order_id" in filters:
            filter_conditions.append(self.model.order_id == filters["order_id"])
        if "idempotency_key" in filters:
            filter_conditions.append(self.model.idempotency_key == filters["idempotency_key"])

        return filter_conditions

    async def list_for_order(self, merchant_id: UUID, order_id: UUID) -> list[Fulfillment]:
        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.merchant_id == merchant_id, self.model.order_id == order_id)
            .order_by(self.model.delivery_date.desc(), self.model.id.desc())
        )

        return list(rows)

    async def list_fulfillments(
        self, merchant_id: UUID, query: FulfillmentListQuery
    ) -> tuple[list[Fulfillment], int]:
        conditions: list[Any] = [self.model.merchant_id == merchant_id]

        if query.order_id:
            conditions.append(self.model.order_id == query.order_id)
        if query.transaction_id:
            conditions.append(self.model.transaction_id == query.transaction_id)

        sort_column = (
            self.model.created_at
            if query.sort.lstrip("-") == "created_at"
            else self.model.delivery_date
        )
        # id breaks ties so pages never repeat or skip rows
        order_by = (
            (sort_column.desc(), self.model.id.desc())
            if query.sort.startswith("-")
            else (sort_column.asc(), self.model.id.asc())
        )

        stmt: Select = select(self.model).where(*conditions).order_by(*order_by)
        rows, total = await self._paginate(
            stmt,
            select(func.count(self.model.id)).where(*conditions),
            query.page,
            query.limit,
        )

        return [row[0] for row in rows], total
