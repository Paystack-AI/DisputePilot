import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.schemas.merchants import MerchantOnboardingInDB
from app.core.exceptions import ServerError


class MerchantOnboardingService:
    def __init__(self, onboarding_repo: MerchantOnboardingRepository):
        self._onboarding_repo = onboarding_repo

    async def _get_onboarding(self, **filters) -> MerchantOnboarding | None:
        return await self._onboarding_repo.get_record(**filters)

    async def create_onboarding(
        self, onboarding: MerchantOnboardingInDB, commit: bool = False
    ) -> MerchantOnboarding:
        try:
            onboarding: MerchantOnboarding = self._onboarding_repo.add(entity=onboarding)

            if commit:
                await self._onboarding_repo.commit()
            else:
                await self._onboarding_repo.flush()
            await self._onboarding_repo.refresh(onboarding)

            return onboarding
        except Exception as exc:
            if commit:
                await self._onboarding_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating merchant onboarding")
            raise ServerError() from exc

    async def update_onboarding(
        self, onboarding: MerchantOnboarding, commit: bool = False
    ) -> MerchantOnboarding:
        try:
            onboarding: MerchantOnboarding = self._onboarding_repo.add(model=onboarding)

            if commit:
                await self._onboarding_repo.commit()
            else:
                await self._onboarding_repo.flush()
            await self._onboarding_repo.refresh(onboarding)

            return onboarding
        except Exception as exc:
            if commit:
                await self._onboarding_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while updating merchant onboarding")
            raise ServerError() from exc
