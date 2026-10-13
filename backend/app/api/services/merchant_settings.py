import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.merchant_settings import MerchantSettings
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.schemas.merchants import MerchantSettingsInDB
from app.core.exceptions import ServerError


class MerchantSettingsService:
    def __init__(self, settings_repo: MerchantSettingsRepository):
        self._settings_repo = settings_repo

    async def _get_merchant_settings(self, **filters) -> MerchantSettings | None:
        return await self._settings_repo.get_record(**filters)

    async def create_merchant_settings(
        self, settings: MerchantSettingsInDB, commit: bool = False
    ) -> MerchantSettings:
        try:
            settings: MerchantSettings = self._settings_repo.add(entity=settings)

            if commit:
                await self._settings_repo.commit()
            else:
                await self._settings_repo.flush()
            await self._settings_repo.refresh(settings)

            return settings
        except Exception as exc:
            if commit:
                await self._settings_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating merchant settings")
            raise ServerError() from exc

    async def update_merchant_settings(
        self, settings: MerchantSettings, commit: bool = False
    ) -> MerchantSettings:
        try:
            settings: MerchantSettings = self._settings_repo.add(model=settings)

            if commit:
                await self._settings_repo.commit()
            else:
                await self._settings_repo.flush()
            await self._settings_repo.refresh(settings)

            return settings
        except Exception as exc:
            if commit:
                await self._settings_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while updating merchant settings")
            raise ServerError() from exc
