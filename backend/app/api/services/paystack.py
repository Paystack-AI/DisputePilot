from datetime import UTC, datetime

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from httpx import AsyncClient

from app.api.clients.paystack import AsyncPaystackClient, PaystackAuthError, PaystackError
from app.api.models.enums import OnboardingStep, PaystackMode
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchants import Merchant
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.repo.merchants import MerchantRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.merchants import PaystackConnection
from app.api.schemas.paystack import PaystackConnect
from app.api.services.merchant_onboarding import MerchantOnboardingService
from app.api.services.merchants import MerchantService
from app.core.exceptions import (
    MerchantExistsError,
    PaystackIntegrationMismatchError,
    PaystackKeyInvalidError,
    PaystackUpstreamError,
    ServerError,
)
from app.core.security import Security


class PaystackService:
    def __init__(self, paystack_http: AsyncClient):
        self._uow = None
        self._paystack_http = paystack_http

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_merchant_onboarding(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        merchant_repo = self._uow.repo(MerchantRepository)
        onboarding_repo = self._uow.repo(MerchantOnboardingRepository)

        self._merchant_service = MerchantService(merchant_repo=merchant_repo)
        self._onboarding_service = MerchantOnboardingService(onboarding_repo=onboarding_repo)

    @staticmethod
    def _to_connection(merchant: Merchant) -> PaystackConnection:
        return PaystackConnection(
            connected=merchant.paystack_secret_key is not None,
            integration_id=merchant.paystack_integration_id,
            mode=merchant.paystack_mode,
            connected_at=merchant.paystack_connected_at,
        )

    async def _validate_secret_key(
        self, secret_key: str, curr_merchant: Merchant
    ) -> tuple[PaystackMode, str | None]:
        """Returns the mode of a usable secret key and its integration id, which is only
        known once the account has a transaction (paystack has no endpoint for it)"""
        merchant_id: str = str(curr_merchant.id)
        client = AsyncPaystackClient(secret_key, self._paystack_http)

        try:
            transactions: dict = await client.list_transactions(per_page=1)
        except PaystackAuthError as exc:
            sentry_logger.error(
                "Paystack rejected the secret key for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise PaystackKeyInvalidError() from exc
        except PaystackError as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Paystack key check failed for merchant {merchant_id}: {status_code}",
                merchant_id=merchant_id,
                status_code=str(exc.status_code),
            )
            raise PaystackUpstreamError() from exc

        integration_id: str | None = None
        if transactions.get("data"):
            integration = transactions["data"][0].get("integration")
            integration_id = str(integration) if integration is not None else None

        # rotating must keep the same paystack account
        if (
            integration_id
            and curr_merchant.paystack_integration_id
            and integration_id != curr_merchant.paystack_integration_id
        ):
            sentry_logger.error(
                "Secret key for merchant {merchant_id} belongs to another integration",
                merchant_id=merchant_id,
            )
            raise PaystackIntegrationMismatchError()

        mode = PaystackMode.LIVE if secret_key.startswith("sk_live_") else PaystackMode.TEST
        return mode, integration_id

    async def connect(
        self,
        curr_merchant: Merchant,
        connect_payload: PaystackConnect,
        security: Security,
        uow: UnitOfWorkRepository,
    ) -> PaystackConnection:
        """Connect or rotate the merchant's secret key"""
        merchant_id: str = str(curr_merchant.id)
        mode, integration_id = await self._validate_secret_key(
            connect_payload.secret_key, curr_merchant
        )

        try:
            await self._uow_merchant_onboarding(uow)

            now: datetime = datetime.now(UTC)

            curr_merchant.paystack_secret_key = await security.encrypt_secret_key(
                connect_payload.secret_key
            )
            curr_merchant.paystack_mode = mode
            if integration_id:
                # another merchant holding this integration raises MerchantExistsError
                curr_merchant.paystack_integration_id = integration_id
            curr_merchant.paystack_connected_at = now
            curr_merchant.updated_at = now
            merchant: Merchant = await self._merchant_service.update_merchant(curr_merchant)

            onboarding: MerchantOnboarding | None = await self._onboarding_service._get_onboarding(
                merchant_id=curr_merchant.id, for_update=True
            )

            # first connection moves onboarding on; rotating the key later does not
            rotated_after_onboarding_sync: bool = onboarding is not None and (
                onboarding.current_step
                not in (OnboardingStep.CONNECT_PAYSTACK, OnboardingStep.CONFIGURE_NOTIFICATIONS)
            )

            if onboarding and onboarding.current_step == OnboardingStep.CONNECT_PAYSTACK:
                onboarding.current_step = OnboardingStep.CONFIGURE_NOTIFICATIONS
                onboarding.updated_at = now
                await self._onboarding_service.update_onboarding(onboarding)

            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()

            if isinstance(exc, MerchantExistsError):
                raise

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while connecting paystack for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise ServerError() from exc

        if rotated_after_onboarding_sync:
            # during onboarding the initial sync starts at the notifications step
            # (POST /onboarding/notifications); after that, a new key needs its own sync
            # TODO: enqueue the transaction sync celery task for the merchant
            sentry_logger.info(
                "Transaction sync requested after key rotation for merchant {merchant_id}",
                merchant_id=merchant_id,
            )

        sentry_logger.info(
            "Paystack {mode} key connected for merchant {merchant_id}",
            mode=mode,
            merchant_id=merchant_id,
        )

        return self._to_connection(merchant)

    async def get_connection(self, curr_merchant: Merchant) -> PaystackConnection:
        return self._to_connection(curr_merchant)
