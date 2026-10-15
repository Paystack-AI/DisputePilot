from datetime import UTC, datetime

import sentry_sdk.logger as sentry_logger

from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.settings import SettingsResponse, SettingsUpdate
from app.api.services.merchant_settings import MerchantSettingsService
from app.core.exceptions import ServerError


class SettingsService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_settings(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        settings_repo = self._uow.repo(MerchantSettingsRepository)
        self._settings_service = MerchantSettingsService(settings_repo=settings_repo)

    async def _get_settings(self, merchant: Merchant) -> MerchantSettings:
        settings: MerchantSettings | None = await self._settings_service._get_merchant_settings(
            merchant_id=merchant.id
        )

        if not settings:
            sentry_logger.error(
                "Settings missing for merchant {merchant_id}", merchant_id=str(merchant.id)
            )
            raise ServerError()

        return settings

    async def get_settings(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> SettingsResponse:
        await self._uow_settings(uow)

        settings: MerchantSettings = await self._get_settings(curr_merchant)

        sentry_logger.info(
            "Merchant {merchant_id} settings retrieved", merchant_id=str(curr_merchant.id)
        )

        return SettingsResponse.model_validate(settings)

    async def update_settings(
        self, curr_merchant: Merchant, update_payload: SettingsUpdate, uow: UnitOfWorkRepository
    ) -> SettingsResponse:
        await self._uow_settings(uow)

        merchant_id: str = str(curr_merchant.id)
        # unset fields are left alone; an explicit null whatsapp number disables whatsapp
        changes: dict = update_payload.model_dump(exclude_unset=True)

        settings: MerchantSettings = await self._get_settings(curr_merchant)

        if changes:
            for field, value in changes.items():
                setattr(settings, field, value)
            settings.updated_at = datetime.now(UTC)

            settings = await self._settings_service.update_merchant_settings(settings, commit=True)

        sentry_logger.info("Merchant {merchant_id} settings updated", merchant_id=merchant_id)

        return SettingsResponse.model_validate(settings)
