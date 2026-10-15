from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository
from app.api.schemas.pagination import PageParams


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

        total: int = await self._async_session.scalar(
            select(func.count(self.model.id)).where(*conditions)
        )
        rows = await self._async_session.scalars(
            select(self.model)
            .where(*conditions)
            # newest payment first; id breaks ties so pages never repeat or skip rows
            .order_by(self.model.paid_at.desc().nulls_last(), self.model.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )

        return list(rows), total

    async def list_for_order(self, merchant_id: UUID, order_id: UUID) -> list[Transaction]:
        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.merchant_id == merchant_id, self.model.order_id == order_id)
            .order_by(self.model.paid_at.desc().nulls_last(), self.model.id.desc())
        )

        return list(rows)
