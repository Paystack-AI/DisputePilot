from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse


class AppException(Exception):
    """Base Exception class"""

    def __init__(self, code: str):
        self.code = code


class ServerError(AppException):
    """Internal Server error."""

    def __init__(self):
        super().__init__("INTERNAL_ERROR")


class AuthenticationError(AppException):
    """Merchant not authenticated: missing, malformed or revoked token."""

    def __init__(self):
        super().__init__("TOKEN_INVALID")


class TokenExpiredError(AppException):
    """Token signature is valid but it has expired."""

    def __init__(self):
        super().__init__("TOKEN_EXPIRED")


class CredentialError(AppException):
    """Wrong credentials provided."""

    def __init__(self):
        super().__init__("INVALID_CREDENTIALS")


class MerchantExistsError(AppException):
    """Merchant already exists with the email (or a unique paystack detail)."""

    def __init__(self):
        super().__init__("MERCHANT_EXISTS")


class InvalidOtpError(AppException):
    """Otp is wrong, expired or was never issued."""

    def __init__(self):
        super().__init__("INVALID_OTP")


class OtpAttemptsExceededError(AppException):
    """Too many wrong otp attempts; a new code must be requested."""

    def __init__(self):
        super().__init__("OTP_ATTEMPTS_EXCEEDED")


class EmailNotVerifiedError(AppException):
    """Merchant has not verified their email."""

    def __init__(self):
        super().__init__("EMAIL_NOT_VERIFIED")


class AccountDeactivatedError(AppException):
    """Merchant account is deactivated."""

    def __init__(self):
        super().__init__("ACCOUNT_DEACTIVATED")


class InvalidOAuthCodeError(AppException):
    """Google sign in code or sign up token is wrong, expired or already used."""

    def __init__(self):
        super().__init__("INVALID_OAUTH_CODE")


class PasswordLoginRequiredError(AppException):
    """Password changes need a session that signed in with email and password."""

    def __init__(self):
        super().__init__("PASSWORD_LOGIN_REQUIRED")


class OnboardingStepMismatchError(AppException):
    """Onboarding action called while the merchant is on another step."""

    def __init__(self, current_step: str):
        super().__init__("ONBOARDING_STEP_MISMATCH")
        self.current_step = current_step
        # lets the client redirect to the step the merchant is actually on
        self.details = {"current_step": current_step}


class NotFoundError(AppException):
    """Record does not exist or belongs to another merchant (existence is not revealed)."""

    def __init__(self, resource: str):
        super().__init__("NOT_FOUND")
        self.resource = resource


class CustomerExistsError(AppException):
    """The merchant already has a customer with this email."""

    def __init__(self, customer_id: str):
        super().__init__("CUSTOMER_EXISTS")
        # lets the client open the existing customer instead
        self.details = {"customer_id": customer_id}


class CustomerEmailLockedError(AppException):
    """Email identifies a customer with synced payments, so it can not change."""

    def __init__(self):
        super().__init__("CUSTOMER_EMAIL_LOCKED")


class OrderNumberExistsError(AppException):
    """The merchant already has an order with this number (case-insensitive)."""

    def __init__(self):
        super().__init__("ORDER_NUMBER_EXISTS")


class OrderLinkedError(AppException):
    """Order is linked to a transaction; matched fields can not change until it is unlinked."""

    def __init__(self, fields: list[str]):
        super().__init__("ORDER_LINKED")
        self.details = {"fields": ", ".join(fields)}


class OrderStatusTransitionError(AppException):
    """Status change the merchant can not make (paid is set by reconciliation)."""

    def __init__(self, current_status: str, new_status: str):
        super().__init__("ORDER_STATUS_TRANSITION")
        self.current_status = current_status
        self.new_status = new_status
        self.details = {"current_status": current_status}


class MatchConflictError(AppException):
    """The payment can not be matched to this order; reason says why."""

    def __init__(self, reason: str):
        super().__init__("MATCH_CONFLICT")
        # order_cancelled | currency_mismatch | transaction_not_successful |
        # already_matched_to_another_order
        self.details = {"reason": reason}


class PaystackNotConnectedError(AppException):
    """The action needs a connected Paystack account."""

    def __init__(self):
        super().__init__("PAYSTACK_NOT_CONNECTED")


class SyncInProgressError(AppException):
    """The initial transaction sync is still running."""

    def __init__(self):
        super().__init__("SYNC_IN_PROGRESS")


class PaystackKeyInvalidError(AppException):
    """Paystack rejected the secret key (wrong, revoked or from a deleted account)."""

    def __init__(self):
        super().__init__("PAYSTACK_KEY_INVALID")


class PaystackIntegrationMismatchError(AppException):
    """The key belongs to a different Paystack account than the one already connected."""

    def __init__(self):
        super().__init__("PAYSTACK_INTEGRATION_MISMATCH")


class PaystackUpstreamError(AppException):
    """Paystack could not be reached or failed; the request can be tried again."""

    def __init__(self):
        super().__init__("PAYSTACK_UPSTREAM_ERROR")


class StorageUpstreamError(AppException):
    """Object storage (minio) could not be reached or failed; the request can be retried."""

    def __init__(self):
        super().__init__("STORAGE_UPSTREAM_ERROR")


class RateLimitExceeded(AppException):
    def __init__(self, retry_after: int):
        super().__init__("RATE_LIMITED")
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


def exception_handler(
    code: int, detail: dict
) -> Callable[[Request, AppException], Awaitable[JSONResponse]]:
    async def _handler(request: Request, exc: AppException):
        message = detail.get("message").format(**exc.__dict__)
        error = Error(
            code=exc.code or detail.get("code"),
            message=message,
            request_id=request.state.request_id,
            details=getattr(exc, "details", None),
        )

        content = ErrorResponse(error=error)
        return JSONResponse(
            content=content.model_dump(mode="json"),
            status_code=code,
            headers=getattr(exc, "headers", None),
        )

    return _handler
