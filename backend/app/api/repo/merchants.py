from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.api.models.merchants import Merchant
from app.api.repo.base import BaseRepository
from app.api.schemas.merchants import MerchantInDB


class MerchantRepository(BaseRepository[MerchantInDB, Merchant]):
    model = Merchant

    @staticmethod
    def _entity_to_model(entity: MerchantInDB) -> model:
        return Merchant(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "email" in filters:
            filter_conditions.append(self.model.email == filters["email"])
        if "google_id" in filters:
            filter_conditions.append(self.model.google_id == filters["google_id"])
        if "google_email" in filters:
            filter_conditions.append(self.model.google_email == filters["google_email"])
        if "webhook_token" in filters:
            filter_conditions.append(self.model.webhook_token == filters["webhook_token"])
        if "paystack_integration_id" in filters:
            filter_conditions.append(
                self.model.paystack_integration_id == filters["paystack_integration_id"]
            )

        return filter_conditions

    async def get_profile(self, merchant_id: UUID) -> Merchant | None:
        """id, business name and paystack integration id only (no key, no password hash),
        for documents and events"""
        return await self._async_session.scalar(
            select(Merchant)
            .options(
                load_only(Merchant.id, Merchant.business_name, Merchant.paystack_integration_id)
            )
            .where(Merchant.id == merchant_id)
        )
