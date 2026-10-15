from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.api.models.fulfillments import Fulfillment
from app.api.repo.base import BaseRepository


class FulfillmentRepository(BaseRepository[BaseModel, Fulfillment]):
    """Read side only for now; the fulfillments module writes them"""

    model = Fulfillment

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return Fulfillment(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "order_id" in filters:
            filter_conditions.append(self.model.order_id == filters["order_id"])

        return filter_conditions

    async def list_for_order(self, merchant_id: UUID, order_id: UUID) -> list[Fulfillment]:
        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.merchant_id == merchant_id, self.model.order_id == order_id)
            .order_by(self.model.delivery_date.desc(), self.model.id.desc())
        )

        return list(rows)
