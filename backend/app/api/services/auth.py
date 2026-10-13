from datetime import UTC, datetime
from uuid import UUID, uuid4

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.enums import OtpPurpose, UserType
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.repo.merchants import MerchantRepository
from app.api.repo.redis import RedisRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.auth import (
    AccountDeactivate,
    EmailLogin,
    EmailSignUp,
    PasswordReset,
    PasswordResetRequest,
    TokenData,
)
from app.api.schemas.merchants import (
    MerchantInDB,
    MerchantOnboardingInDB,
    MerchantResponse,
    MerchantSettingsInDB,
    MerchantUpdate,
    OnboardingStatus,
    PaystackConnection,
)
from app.api.schemas.otp import EmailVerify, ResendOtp
from app.api.services.merchant_onboarding import MerchantOnboardingService
from app.api.services.merchant_settings import MerchantSettingsService
from app.api.services.merchants import MerchantService
from app.api.services.otp import OtpService
from app.core.config import get_settings
from app.core.exceptions import (
    AccountDeactivatedError,
    AuthenticationError,
    CredentialError,
    EmailNotVerifiedError,
    InvalidOtpError,
    MerchantExistsError,
    ServerError,
)
from app.core.security import Security


class AuthService:
    def __init__(self, redis_repo: RedisRepository):
        self._uow = None
        self._redis_repo = redis_repo
        self._otp_service = OtpService(redis_repo=redis_repo)

    SETTINGS = get_settings()

    @staticmethod
    def _sessions_key(merchant_id: str) -> str:
        """Hash of a merchant's active sessions: session id -> current refresh token id.

        Tokens are only accepted while their session is in here, so deleting a
        field ends one session and deleting the hash ends all of them.
        """
        return f"sessions:{merchant_id}"

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_merchant(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        merchant_repo = self._uow.repo(MerchantRepository)
        self._merchant_service = MerchantService(merchant_repo=merchant_repo)

    async def _uow_merchant_settings_onboarding(self, uow: UnitOfWorkRepository):
        await self._uow_merchant(uow)

        settings_repo = self._uow.repo(MerchantSettingsRepository)
        onboarding_repo = self._uow.repo(MerchantOnboardingRepository)

        self._settings_service = MerchantSettingsService(settings_repo=settings_repo)
        self._onboarding_service = MerchantOnboardingService(onboarding_repo=onboarding_repo)

    async def _create_session(self, merchant_id: UUID, user_type: str, security: Security):
        """Start a new session (login / sign up) and return its tokens"""
        token_data: TokenData = TokenData(
            merchant_id=merchant_id, user_type=user_type, session_id=uuid4()
        )
        access_token, refresh_token_payload = await security.prepare_tokens(token_data)

        try:
            await self._redis_repo.create_hset(
                self._sessions_key(str(merchant_id)),
                {refresh_token_payload["session_id"]: refresh_token_payload["refresh_token_id"]},
                refresh_token_payload["refresh_token_expire_time"],
            )
            return access_token, refresh_token_payload["refresh_token"]
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occurred while saving session to redis")
            raise ServerError() from exc

    async def _end_session(self, merchant_id: str, session_id: str):
        try:
            await self._redis_repo.delete_hash_field(self._sessions_key(merchant_id), session_id)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occurred while ending session for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise ServerError() from exc

    async def _end_all_sessions(self, merchant_id: str):
        try:
            await self._redis_repo.delete_key(self._sessions_key(merchant_id))
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occurred while ending sessions for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise ServerError() from exc

    async def verify_access_token(self, access_token_claims: dict):
        """Reject access tokens whose session has ended (logout, password change)"""
        merchant_id: str = access_token_claims["sub"]

        try:
            session_active: bool = await self._redis_repo.hash_field_exists(
                self._sessions_key(merchant_id), access_token_claims["sid"]
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occurred while checking session")
            raise ServerError() from exc

        if not session_active:
            sentry_logger.error(
                "Access token for an ended session received for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise AuthenticationError()

    @staticmethod
    def _to_merchant_response(
        merchant: Merchant, settings: MerchantSettings, onboarding: MerchantOnboarding
    ) -> MerchantResponse:
        return MerchantResponse(
            id=merchant.id,
            email=merchant.email,
            google_email=merchant.google_email,
            business_name=merchant.business_name,
            paystack=PaystackConnection(
                connected=merchant.paystack_secret_key is not None,
                integration_id=merchant.paystack_integration_id,
                mode=merchant.paystack_mode,
                connected_at=merchant.paystack_connected_at,
            ),
            timezone=settings.timezone,
            default_currency=settings.default_currency,
            onboarding=OnboardingStatus(
                completed=onboarding.completed_at is not None,
                next_step=onboarding.current_step,
            ),
            created_at=merchant.created_at,
        )

    async def _send_otp(self, merchant: Merchant, purpose: OtpPurpose):
        otp: str = await self._otp_service.create_otp(merchant.id, purpose)  # noqa: F841

        # TODO: enqueue the send_email celery task (Resend) with the otp, the same way
        # as Ledger: create an emails record for delivery status, then
        # send_email.apply_async(kwargs={..., "email_id": ..., "recipient_email": merchant.email})
        sentry_logger.info(
            "{purpose} otp created for merchant {merchant_id}",
            purpose=purpose,
            merchant_id=str(merchant.id),
        )

    async def _authenticate(
        self, email: str, password: str, merchant_service: MerchantService, security: Security
    ) -> Merchant:
        """Check email and password; account status is checked by the caller"""
        merchant: Merchant | None = await merchant_service._get_merchant(email=email)

        if not merchant or not merchant.hashed_password:
            sentry_logger.error("Invalid credentials received")
            raise CredentialError()

        if not await security.verify_password(password, merchant.hashed_password):
            sentry_logger.error(
                "Invalid credentials received for merchant {merchant_id}",
                merchant_id=str(merchant.id),
            )
            raise CredentialError()

        return merchant

    async def sign_up_with_email(
        self, sign_up_payload: EmailSignUp, security: Security, uow: UnitOfWorkRepository
    ):
        try:
            await self._uow_merchant_settings_onboarding(uow)

            hashed_password: str = await security.hash_password(sign_up_payload.password)

            existing_merchant: Merchant | None = await self._merchant_service._get_merchant(
                email=sign_up_payload.email
            )

            if existing_merchant and existing_merchant.is_verified:
                raise MerchantExistsError()

            if existing_merchant:
                # never verified: take the latest details and send a new code
                existing_merchant.hashed_password = hashed_password
                existing_merchant.business_name = sign_up_payload.business_name
                existing_merchant.updated_at = datetime.now(UTC)

                merchant: Merchant = await self._merchant_service.update_merchant(existing_merchant)
            else:
                merchant = MerchantInDB(
                    email=sign_up_payload.email,
                    hashed_password=hashed_password,
                    business_name=sign_up_payload.business_name,
                )

                # merchant, settings and onboarding are created together or not at all
                merchant: Merchant = await self._merchant_service.create_merchant(merchant)
                await self._settings_service.create_merchant_settings(
                    MerchantSettingsInDB(merchant_id=merchant.id)
                )
                await self._onboarding_service.create_onboarding(
                    MerchantOnboardingInDB(merchant_id=merchant.id)
                )

            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()

            if isinstance(exc, MerchantExistsError):
                sentry_logger.error("Merchant already exists with the provided details")
                raise

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating merchant")
            raise ServerError() from exc

        await self._send_otp(merchant, OtpPurpose.EMAIL_VERIFICATION)

        sentry_logger.info(
            "Email and password sign up completed for merchant {merchant_id}",
            merchant_id=str(merchant.id),
        )

    async def resend_verification_otp(
        self, otp_resend: ResendOtp, merchant_service: MerchantService
    ):
        merchant: Merchant | None = await merchant_service._get_merchant(email=otp_resend.email)

        # same response whether or not the email exists, so it can not be probed
        if not merchant or merchant.is_verified:
            sentry_logger.info("Verification otp resend requested for no unverified merchant")
            return

        await self._send_otp(merchant, OtpPurpose.EMAIL_VERIFICATION)

    async def verify_account(self, email_verify: EmailVerify, uow: UnitOfWorkRepository):
        await self._uow_merchant(uow)

        merchant: Merchant | None = await self._merchant_service._get_merchant(
            email=email_verify.email
        )

        if not merchant or merchant.is_verified:
            sentry_logger.error("Verification otp received for no unverified merchant")
            raise InvalidOtpError()

        await self._otp_service.verify_otp(
            merchant.id, OtpPurpose.EMAIL_VERIFICATION, email_verify.otp_code
        )

        merchant.is_verified = True
        merchant.updated_at = datetime.now(UTC)
        await self._merchant_service.update_merchant(merchant, commit=True)

        sentry_logger.info(
            "Merchant {merchant_id} account verification completed",
            merchant_id=str(merchant.id),
        )

    async def login(
        self, email_login: EmailLogin, merchant_service: MerchantService, security: Security
    ) -> tuple[str, str]:
        merchant: Merchant = await self._authenticate(
            email_login.email, email_login.password, merchant_service, security
        )

        # checked after the password so account status is not revealed to guessers
        if not merchant.is_verified:
            raise EmailNotVerifiedError()
        if not merchant.is_active:
            raise AccountDeactivatedError()

        access_token, refresh_token = await self._create_session(
            merchant.id, UserType.EMAIL, security
        )

        sentry_logger.info(
            "Login completed for merchant {merchant_id}", merchant_id=str(merchant.id)
        )

        return access_token, refresh_token

    async def create_auth_tokens(
        self, refresh_token: str, merchant_service: MerchantService, security: Security
    ) -> tuple[str, str]:
        claims: dict | None = await security.decode_token(
            refresh_token, self.SETTINGS.REFRESH_TOKEN_SECRET_KEY
        )

        if not claims:
            sentry_logger.error("Invalid refresh token received")
            raise AuthenticationError()

        merchant_id: str = claims["sub"]
        merchant: Merchant | None = await merchant_service._get_merchant(id=UUID(merchant_id))

        if not merchant:
            sentry_logger.error(
                "Merchant {merchant_id} not found during refresh", merchant_id=merchant_id
            )
            raise AuthenticationError()

        # same session, new token pair
        token_data: TokenData = TokenData(
            merchant_id=merchant.id, user_type=claims["usertype"], session_id=claims["sid"]
        )
        access_token, refresh_token_payload = await security.prepare_tokens(token_data)

        try:
            # the received token must be the session's current one; it is swapped for
            # the new one in the same step so it can never be used twice
            rotated: int = await self._redis_repo.rotate_hash_field(
                self._sessions_key(merchant_id),
                claims["sid"],
                claims["jti"],
                refresh_token_payload["refresh_token_id"],
                refresh_token_payload["refresh_token_expire_time"],
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occurred while rotating refresh token")
            raise ServerError() from exc

        if rotated == 0:
            sentry_logger.error(
                "Refresh token for an ended session received for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise AuthenticationError()

        if rotated == -1:
            # an already rotated token was replayed, so the session it belongs to
            # was ended in case the token was stolen; other devices stay signed in
            sentry_logger.error(
                "Reused refresh token received for merchant {merchant_id}",
                merchant_id=merchant_id,
            )
            raise AuthenticationError()

        refresh_token: str = refresh_token_payload["refresh_token"]

        sentry_logger.info(
            "Access and refresh tokens created for merchant {merchant_id}",
            merchant_id=merchant_id,
        )

        return access_token, refresh_token

    async def get_current_merchant(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> MerchantResponse:
        await self._uow_merchant_settings_onboarding(uow)

        settings: MerchantSettings | None = await self._settings_service._get_merchant_settings(
            merchant_id=curr_merchant.id
        )
        onboarding: MerchantOnboarding | None = await self._onboarding_service._get_onboarding(
            merchant_id=curr_merchant.id
        )

        if not settings or not onboarding:
            sentry_logger.error(
                "Settings or onboarding missing for merchant {merchant_id}",
                merchant_id=str(curr_merchant.id),
            )
            raise ServerError()

        sentry_logger.info(
            "Merchant {merchant_id} account retrieved", merchant_id=str(curr_merchant.id)
        )

        return self._to_merchant_response(curr_merchant, settings, onboarding)

    async def update_current_merchant(
        self,
        curr_merchant: Merchant,
        update_payload: MerchantUpdate,
        security: Security,
        uow: UnitOfWorkRepository,
    ) -> MerchantResponse:
        await self._uow_merchant(uow)

        merchant_id: str = str(curr_merchant.id)
        changes: dict = update_payload.model_dump(exclude_none=True, exclude={"current_password"})

        if "password" in changes:
            current_password: str | None = update_payload.current_password

            if (
                not current_password
                or not curr_merchant.hashed_password
                or not await security.verify_password(
                    current_password, curr_merchant.hashed_password
                )
            ):
                sentry_logger.error(
                    "Invalid current password received for merchant {merchant_id}",
                    merchant_id=merchant_id,
                )
                raise CredentialError()

        if "business_name" in changes:
            curr_merchant.business_name = changes["business_name"]
        if "password" in changes:
            curr_merchant.hashed_password = await security.hash_password(changes["password"])

        if changes:
            curr_merchant.updated_at = datetime.now(UTC)
            curr_merchant = await self._merchant_service.update_merchant(curr_merchant, commit=True)

        if "password" in changes:
            # sign out every session opened with the old password, including this one
            await self._end_all_sessions(merchant_id)

        sentry_logger.info("Merchant {merchant_id} account updated", merchant_id=merchant_id)

        return await self.get_current_merchant(curr_merchant, uow)

    async def logout(self, access_token_claims: dict):
        """End the session the access token belongs to, revoking its tokens"""
        merchant_id: str = access_token_claims["sub"]
        await self._end_session(merchant_id, access_token_claims["sid"])

        sentry_logger.info(
            "Merchant {merchant_id} account logout completed", merchant_id=merchant_id
        )

    async def request_password_reset(
        self, reset_request: PasswordResetRequest, merchant_service: MerchantService
    ):
        merchant: Merchant | None = await merchant_service._get_merchant(email=reset_request.email)

        # same response whether or not the email exists, so it can not be probed
        if (
            not merchant
            or not merchant.hashed_password
            or not merchant.is_verified
            or not merchant.is_active
        ):
            sentry_logger.info("Password reset requested for no eligible merchant")
            return

        await self._send_otp(merchant, OtpPurpose.PASSWORD_RESET)

    async def reset_password(
        self, password_reset: PasswordReset, security: Security, uow: UnitOfWorkRepository
    ):
        await self._uow_merchant(uow)

        merchant: Merchant | None = await self._merchant_service._get_merchant(
            email=password_reset.email
        )

        if not merchant or not merchant.is_verified or not merchant.is_active:
            sentry_logger.error("Password reset otp received for no eligible merchant")
            raise InvalidOtpError()

        await self._otp_service.verify_otp(
            merchant.id, OtpPurpose.PASSWORD_RESET, password_reset.otp_code
        )

        merchant.hashed_password = await security.hash_password(password_reset.password)
        merchant.updated_at = datetime.now(UTC)
        await self._merchant_service.update_merchant(merchant, commit=True)

        # whoever knew the old password is signed out
        await self._end_all_sessions(str(merchant.id))

        sentry_logger.info(
            "Password reset completed for merchant {merchant_id}", merchant_id=str(merchant.id)
        )

    async def deactivate_account(
        self,
        curr_merchant: Merchant,
        deactivate_payload: AccountDeactivate,
        security: Security,
        uow: UnitOfWorkRepository,
    ):
        await self._uow_merchant(uow)
        merchant_id: str = str(curr_merchant.id)

        if not curr_merchant.hashed_password or not await security.verify_password(
            deactivate_payload.password, curr_merchant.hashed_password
        ):
            sentry_logger.error(
                "Invalid password received for merchant {merchant_id} deactivation",
                merchant_id=merchant_id,
            )
            raise CredentialError()

        # soft delete: data is kept so the merchant can reactivate
        curr_merchant.is_active = False
        curr_merchant.deactivated_at = datetime.now(UTC)
        curr_merchant.updated_at = curr_merchant.deactivated_at
        await self._merchant_service.update_merchant(curr_merchant, commit=True)

        await self._end_all_sessions(merchant_id)

        sentry_logger.info("Merchant {merchant_id} account deactivated", merchant_id=merchant_id)

    async def reactivate_account(
        self, email_login: EmailLogin, merchant_service: MerchantService, security: Security
    ) -> tuple[str, str]:
        merchant: Merchant = await self._authenticate(
            email_login.email, email_login.password, merchant_service, security
        )

        if not merchant.is_verified:
            raise EmailNotVerifiedError()

        if not merchant.is_active:
            merchant.is_active = True
            merchant.deactivated_at = None
            merchant.updated_at = datetime.now(UTC)
            await merchant_service.update_merchant(merchant, commit=True)

        access_token, refresh_token = await self._create_session(
            merchant.id, UserType.EMAIL, security
        )

        sentry_logger.info(
            "Merchant {merchant_id} account reactivated", merchant_id=str(merchant.id)
        )

        return access_token, refresh_token
