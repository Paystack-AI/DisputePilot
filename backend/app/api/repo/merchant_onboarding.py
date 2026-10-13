from typing import Any

from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.repo.base import BaseRepository
from app.api.schemas.merchants import MerchantOnboardingInDB


class MerchantOnboardingRepository(BaseRepository[MerchantOnboardingInDB, MerchantOnboarding]):
    model = MerchantOnboarding

    @staticmethod
    def _entity_to_model(entity: MerchantOnboardingInDB) -> model:
        return MerchantOnboarding(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions
