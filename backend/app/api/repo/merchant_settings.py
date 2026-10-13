from typing import Any

from app.api.models.merchant_settings import MerchantSettings
from app.api.repo.base import BaseRepository
from app.api.schemas.merchants import MerchantSettingsInDB


class MerchantSettingsRepository(BaseRepository[MerchantSettingsInDB, MerchantSettings]):
    model = MerchantSettings

    @staticmethod
    def _entity_to_model(entity: MerchantSettingsInDB) -> model:
        return MerchantSettings(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions
