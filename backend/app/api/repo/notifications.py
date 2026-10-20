from typing import Any

from pydantic import BaseModel

from app.api.models.notifications_log import NotificationLog
from app.api.repo.base import BaseRepository


class NotificationLogRepository(BaseRepository[BaseModel, NotificationLog]):
    model = NotificationLog

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return NotificationLog(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions
