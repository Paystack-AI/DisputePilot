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
