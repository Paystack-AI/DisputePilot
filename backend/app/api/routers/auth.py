from fastapi import APIRouter

from app.api.schemas.auth import (
    AccountDeactivate,
    EmailLogin,
    EmailSignUp,
    PasswordReset,
    PasswordResetRequest,
    RefreshToken,
    Token,
)
from app.api.schemas.merchants import MerchantResponse, MerchantUpdate
from app.api.schemas.otp import EmailVerify, OtpSentResponse, ResendOtp
from app.api.schemas.response import SuccessResponse
from app.core.config import get_settings
from app.deps import (
    AccessTokenClaims,
    AuthServiceDep,
    CurrentMerchant,
    MerchantServiceDep,
    SecurityDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

SETTINGS = get_settings()

router = APIRouter()


def _token(access_token: str, refresh_token: str) -> Token:
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=SETTINGS.ACCESS_TOKEN_EXPIRE_TIME * 60,
    )


def _otp_sent(email: str) -> OtpSentResponse:
    return OtpSentResponse(email=email, expires_in=SETTINGS.OTP_EXPIRE_TIME * 60)


@router.post(
    "/auth/register",
    status_code=201,
    response_model=SuccessResponse[OtpSentResponse],
    description=(
        "Sign up with email and password. Creates the merchant with default settings and "
        "onboarding and emails a verification code. Signing up again with an unverified "
        "email updates the details and sends a new code"
    ),
    dependencies=[write_limiter],
)
async def register(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    sign_up_payload: EmailSignUp,
    auth_service: AuthServiceDep,
):
    await auth_service.sign_up_with_email(sign_up_payload, security, uow)
    return SuccessResponse(data=_otp_sent(sign_up_payload.email))


@router.post(
    "/auth/verify",
    status_code=204,
    description="Verify the merchant's email with the emailed code, then log in",
    dependencies=[write_limiter],
)
async def verify_account(
    uow: UnitOfWorkRepo,
    email_verify: EmailVerify,
    auth_service: AuthServiceDep,
):
    await auth_service.verify_account(email_verify, uow)


@router.post(
    "/auth/verify/resend",
    status_code=202,
    response_model=SuccessResponse[OtpSentResponse],
    description=(
        "Send a new verification code, replacing the previous one. "
        "Responds the same whether or not the email is registered"
    ),
    dependencies=[write_limiter],
)
async def resend_verification_otp(
    otp_resend: ResendOtp,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    await auth_service.resend_verification_otp(otp_resend, merchant_service)
    return SuccessResponse(data=_otp_sent(otp_resend.email))


@router.post(
    "/auth/login",
    status_code=200,
    response_model=SuccessResponse[Token],
    description="Login with email and password",
    dependencies=[write_limiter],
)
async def login(
    security: SecurityDep,
    email_login: EmailLogin,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    access_token, refresh_token = await auth_service.login(email_login, merchant_service, security)
    return SuccessResponse(data=_token(access_token, refresh_token))


@router.post(
    "/auth/refresh",
    status_code=200,
    response_model=SuccessResponse[Token],
    description=(
        "Rotate the refresh token and create a new access token. "
        "The submitted refresh token can not be used again"
    ),
    dependencies=[write_limiter],
)
async def create_new_token(
    security: SecurityDep,
    refresh_payload: RefreshToken,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    access_token, refresh_token = await auth_service.create_auth_tokens(
        refresh_payload.refresh_token, merchant_service, security
    )
    return SuccessResponse(data=_token(access_token, refresh_token))


@router.get(
    "/auth/me",
    status_code=200,
    response_model=SuccessResponse[MerchantResponse],
    description="Get current merchant",
    dependencies=[read_limiter],
)
async def get_current_merchant(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    auth_service: AuthServiceDep,
):
    merchant: MerchantResponse = await auth_service.get_current_merchant(curr_merchant, uow)
    return SuccessResponse(data=merchant)


@router.patch(
    "/auth/me",
    status_code=200,
    response_model=SuccessResponse[MerchantResponse],
    description=(
        "Update business name or password. "
        "current_password is required to change password, and a password change "
        "revokes every refresh token and access token, including the current one"
    ),
    dependencies=[write_limiter],
)
async def update_current_merchant(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    curr_merchant: CurrentMerchant,
    update_payload: MerchantUpdate,
    auth_service: AuthServiceDep,
):
    merchant: MerchantResponse = await auth_service.update_current_merchant(
        curr_merchant, update_payload, security, uow
    )
    return SuccessResponse(data=merchant)


@router.post(
    "/auth/logout",
    status_code=204,
    description=(
        "Log out by ending the current session. "
        "Its access and refresh tokens stop working immediately"
    ),
    dependencies=[write_limiter],
)
async def log_out(
    auth_service: AuthServiceDep,
    access_token_claims: AccessTokenClaims,
):
    await auth_service.logout(access_token_claims)


@router.post(
    "/auth/password-reset",
    status_code=202,
    response_model=SuccessResponse[OtpSentResponse],
    description=(
        "Email a password reset code. Responds the same whether or not the email is registered"
    ),
    dependencies=[write_limiter],
)
async def request_password_reset(
    reset_request: PasswordResetRequest,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    await auth_service.request_password_reset(reset_request, merchant_service)
    return SuccessResponse(data=_otp_sent(reset_request.email))


@router.post(
    "/auth/password-reset/confirm",
    status_code=204,
    description="Set a new password with the emailed code. Signs out every session",
    dependencies=[write_limiter],
)
async def reset_password(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    password_reset: PasswordReset,
    auth_service: AuthServiceDep,
):
    await auth_service.reset_password(password_reset, security, uow)


@router.post(
    "/auth/me/deactivate",
    status_code=204,
    description=(
        "Deactivate the account (soft delete). Data is kept, every session is signed "
        "out and the merchant can reactivate with their email and password"
    ),
    dependencies=[write_limiter],
)
async def deactivate_account(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    curr_merchant: CurrentMerchant,
    deactivate_payload: AccountDeactivate,
    auth_service: AuthServiceDep,
):
    await auth_service.deactivate_account(curr_merchant, deactivate_payload, security, uow)


@router.post(
    "/auth/reactivate",
    status_code=200,
    response_model=SuccessResponse[Token],
    description="Reactivate a deactivated account with email and password, then sign in",
    dependencies=[write_limiter],
)
async def reactivate_account(
    security: SecurityDep,
    email_login: EmailLogin,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    access_token, refresh_token = await auth_service.reactivate_account(
        email_login, merchant_service, security
    )
    return SuccessResponse(data=_token(access_token, refresh_token))
