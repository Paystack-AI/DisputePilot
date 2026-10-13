from datetime import UTC, datetime

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.enums import InitialSyncStatus, OnboardingStep
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.onboarding import OnboardingResponse
from app.api.schemas.settings import NotificationPreferences
from app.api.services.merchant_onboarding import MerchantOnboardingService
from app.api.services.merchant_settings import MerchantSettingsService
from app.core.exceptions import OnboardingStepMismatchError, ServerError


class OnboardingService:
    """Onboarding is a fixed sequence of steps:

    connect_paystack -> configure_notifications -> initial_sync -> first_reconciliation
    -> completed

    Each action only runs on its own step, so a client that lost its place
    (closed tab, new login) reads the current step and resumes there.
    """

    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_onboarding_settings(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        onboarding_repo = self._uow.repo(MerchantOnboardingRepository)
        settings_repo = self._uow.repo(MerchantSettingsRepository)

        self._onboarding_service = MerchantOnboardingService(onboarding_repo=onboarding_repo)
        self._settings_service = MerchantSettingsService(settings_repo=settings_repo)

    @staticmethod
    def _to_response(onboarding: MerchantOnboarding) -> OnboardingResponse:
        return OnboardingResponse(
            next_step=onboarding.current_step,
            completed=onboarding.completed_at is not None,
            initial_sync_status=onboarding.initial_sync_status,
            initial_sync_total=onboarding.initial_sync_total,
            initial_sync_processed=onboarding.initial_sync_processed,
            first_reconciliation_skipped=onboarding.first_reconciliation_skipped,
            completed_at=onboarding.completed_at,
        )

    async def _get_onboarding(
        self, merchant: Merchant, for_update: bool = False
    ) -> MerchantOnboarding:
        onboarding: MerchantOnboarding | None = await self._onboarding_service._get_onboarding(
            merchant_id=merchant.id, for_update=for_update
        )

        if not onboarding:
            sentry_logger.error(
                "Onboarding missing for merchant {merchant_id}", merchant_id=str(merchant.id)
            )
            raise ServerError()

        return onboarding

    @staticmethod
    def _require_step(onboarding: MerchantOnboarding, step: OnboardingStep):
        if onboarding.current_step != step:
            sentry_logger.error(
                "Onboarding {step} requested on {current_step} for merchant {merchant_id}",
                step=step,
                current_step=onboarding.current_step,
                merchant_id=str(onboarding.merchant_id),
            )
            raise OnboardingStepMismatchError(onboarding.current_step)

    async def get_onboarding(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> OnboardingResponse:
        await self._uow_onboarding_settings(uow)

        onboarding: MerchantOnboarding = await self._get_onboarding(curr_merchant)
        return self._to_response(onboarding)

    async def configure_notifications(
        self,
        curr_merchant: Merchant,
        preferences: NotificationPreferences,
        uow: UnitOfWorkRepository,
    ) -> OnboardingResponse:
        """Step 2: save notification preferences (an empty body keeps the defaults)
        and start the initial transaction sync"""
        merchant_id: str = str(curr_merchant.id)
        changes: dict = preferences.model_dump(exclude_unset=True)

        try:
            await self._uow_onboarding_settings(uow)

            # locked so a double submit waits here, then fails the step check
            # instead of starting a second sync
            onboarding: MerchantOnboarding = await self._get_onboarding(
                curr_merchant, for_update=True
            )
            self._require_step(onboarding, OnboardingStep.CONFIGURE_NOTIFICATIONS)

            now: datetime = datetime.now(UTC)

            if changes:
                settings: (
                    MerchantSettings | None
                ) = await self._settings_service._get_merchant_settings(
                    merchant_id=curr_merchant.id
                )

                if not settings:
                    sentry_logger.error(
                        "Settings missing for merchant {merchant_id}", merchant_id=merchant_id
                    )
                    raise ServerError()

                for field, value in changes.items():
                    setattr(settings, field, value)
                settings.updated_at = now
                await self._settings_service.update_merchant_settings(settings)

            onboarding.current_step = OnboardingStep.INITIAL_SYNC
            onboarding.updated_at = now

            # a sync left over from an earlier attempt is never started twice
            start_sync: bool = onboarding.initial_sync_status in (
                InitialSyncStatus.NOT_STARTED,
                InitialSyncStatus.FAILED,
            )
            if start_sync:
                onboarding.initial_sync_status = InitialSyncStatus.IN_PROGRESS
                onboarding.initial_sync_processed = 0
                onboarding.initial_sync_total = None

            onboarding = await self._onboarding_service.update_onboarding(onboarding)

            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()

            if isinstance(exc, OnboardingStepMismatchError | ServerError):
                raise

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while configuring notifications for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise ServerError() from exc

        if start_sync:
            # TODO: enqueue the transaction sync celery task (last 30 days) after the commit.
            # The task should:
            #  - set initial_sync_total, then update initial_sync_processed as it goes
            #  - publish progress to the merchant's SSE stream (TODO: GET /events), throttled
            #  - on success set initial_sync_status = completed and
            #    current_step = first_reconciliation
            #  - on failure set initial_sync_status = failed (and decide how a retry is
            #    triggered, since the step has already moved on to initial_sync)
            sentry_logger.info(
                "Initial transaction sync requested for merchant {merchant_id}",
                merchant_id=merchant_id,
            )

        sentry_logger.info(
            "Onboarding notifications configured for merchant {merchant_id}",
            merchant_id=merchant_id,
        )

        return self._to_response(onboarding)

    async def skip_first_reconciliation(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> OnboardingResponse:
        """Step 4: "do it later" finishes onboarding without a first reconciliation"""
        merchant_id: str = str(curr_merchant.id)

        try:
            await self._uow_onboarding_settings(uow)

            onboarding: MerchantOnboarding = await self._get_onboarding(
                curr_merchant, for_update=True
            )
            self._require_step(onboarding, OnboardingStep.FIRST_RECONCILIATION)

            now: datetime = datetime.now(UTC)
            onboarding.first_reconciliation_skipped = True
            onboarding.current_step = OnboardingStep.COMPLETED
            onboarding.completed_at = now
            onboarding.updated_at = now

            onboarding = await self._onboarding_service.update_onboarding(onboarding)

            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()

            if isinstance(exc, OnboardingStepMismatchError | ServerError):
                raise

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while skipping first reconciliation for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise ServerError() from exc

        # TODO: starting the first reconciliation session (POST /reconciliation/start) while
        # on this step should complete onboarding the same way, without the skipped flag

        sentry_logger.info(
            "Onboarding completed for merchant {merchant_id}", merchant_id=merchant_id
        )

        return self._to_response(onboarding)
