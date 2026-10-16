from urllib.parse import urlencode

import httpx
import sentry_sdk.logger as sentry_logger
from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.models.enums import GoogleSignInError, GoogleSignInIntent
from app.api.schemas.auth import (
    AccountDeactivate,
    EmailLogin,
    EmailSignUp,
    GoogleSignInExchange,
    GoogleSignUpComplete,
    PasswordReset,
    PasswordResetRequest,
    Reactivate,
    ReactivateRequest,
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


def _frontend_redirect(params: dict[str, str]) -> RedirectResponse:
    """Back to the frontend's google page with one of code, signup_token or error"""
    return RedirectResponse(
        f"{SETTINGS.FRONTEND_URL}/auth/google?{urlencode(params)}", status_code=302
    )


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
        "Update business name or password. A password change needs current_password and a "
        "session that signed in with email and password (403 PASSWORD_LOGIN_REQUIRED "
        "otherwise), and it revokes every session, including the current one"
    ),
    dependencies=[write_limiter],
)
async def update_current_merchant(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    curr_merchant: CurrentMerchant,
    update_payload: MerchantUpdate,
    auth_service: AuthServiceDep,
    access_token_claims: AccessTokenClaims,
):
    merchant: MerchantResponse = await auth_service.update_current_merchant(
        curr_merchant, update_payload, access_token_claims, security, uow
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
    "/auth/me/deactivate/request",
    status_code=202,
    response_model=SuccessResponse[OtpSentResponse],
    description="Email a code that confirms deactivation, for every account type",
    dependencies=[write_limiter],
)
async def request_deactivation(
    curr_merchant: CurrentMerchant,
    auth_service: AuthServiceDep,
):
    await auth_service.request_deactivation(curr_merchant)
    return SuccessResponse(data=_otp_sent(curr_merchant.email))


@router.post(
    "/auth/me/deactivate",
    status_code=204,
    description=(
        "Deactivate the account (soft delete) with the emailed code. Data is kept, every "
        "session is signed out, and both password and google sign in stop working until "
        "the merchant reactivates"
    ),
    dependencies=[write_limiter],
)
async def deactivate_account(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    deactivate_payload: AccountDeactivate,
    auth_service: AuthServiceDep,
):
    await auth_service.deactivate_account(curr_merchant, deactivate_payload, uow)


@router.post(
    "/auth/reactivate/request",
    status_code=202,
    response_model=SuccessResponse[OtpSentResponse],
    description=(
        "Email a reactivation code to a deactivated password account (email or linked). "
        "Responds the same whether or not the email is registered or uses google only"
    ),
    dependencies=[write_limiter],
)
async def request_reactivation(
    reactivate_request: ReactivateRequest,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    await auth_service.request_reactivation(reactivate_request, merchant_service)
    return SuccessResponse(data=_otp_sent(reactivate_request.email))


@router.post(
    "/auth/reactivate",
    status_code=200,
    response_model=SuccessResponse[Token],
    description=(
        "Reactivate a deactivated password account (email or linked) with the emailed "
        "code, then sign in. Google only accounts reactivate through "
        "GET /auth/google?intent=reactivate"
    ),
    dependencies=[write_limiter],
)
async def reactivate_account(
    security: SecurityDep,
    reactivate_payload: Reactivate,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    access_token, refresh_token = await auth_service.reactivate_account(
        reactivate_payload, merchant_service, security
    )
    return SuccessResponse(data=_token(access_token, refresh_token))


@router.get(
    "/auth/google",
    status_code=302,
    response_class=RedirectResponse,
    description=(
        "Start google sign in (browser navigation, not a fetch). "
        "intent=reactivate also reactivates a deactivated account"
    ),
    dependencies=[write_limiter],
)
async def sign_in_with_google(
    request: Request,
    security: SecurityDep,
    intent: GoogleSignInIntent = GoogleSignInIntent.SIGN_IN,
):
    # kept in the signed session cookie with authlib's state until the callback
    request.session["google_intent"] = intent

    redirect_uri: str = SETTINGS.GOOGLE_REDIRECT_URI or str(request.url_for("google_callback"))
    return await security.oauth.google.authorize_redirect(request, redirect_uri)


@router.get(
    "/auth/google/callback",
    name="google_callback",
    status_code=302,
    response_class=RedirectResponse,
    description=(
        "Google redirects here. Always redirects to {FRONTEND_URL}/auth/google with "
        "code (exchange it), signup_token (complete the sign up) or error"
    ),
    dependencies=[write_limiter],
)
async def google_callback(
    request: Request,
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    auth_service: AuthServiceDep,
):
    intent: str = request.session.pop("google_intent", GoogleSignInIntent.SIGN_IN)

    if request.query_params.get("error"):
        # e.g. the merchant cancelled on google's consent screen
        error: GoogleSignInError = (
            GoogleSignInError.ACCESS_DENIED
            if request.query_params["error"] == "access_denied"
            else GoogleSignInError.OAUTH_FAILED
        )
        return _frontend_redirect({"error": error})

    try:
        # checks the state against the session cookie, then swaps the code for the profile
        token: dict = await security.oauth.google.authorize_access_token(request)
    except (OAuthError, httpx.HTTPError) as exc:
        sentry_logger.error("Google sign in failed: {error}", error=str(exc))
        return _frontend_redirect({"error": GoogleSignInError.OAUTH_FAILED})

    params: dict[str, str] = await auth_service.handle_google_callback(
        token.get("userinfo") or {}, GoogleSignInIntent(intent), uow
    )
    return _frontend_redirect(params)


@router.post(
    "/auth/google/exchange",
    status_code=200,
    response_model=SuccessResponse[Token],
    description="Swap the one-time code from the google redirect for tokens",
    dependencies=[write_limiter],
)
async def exchange_google_code(
    security: SecurityDep,
    exchange_payload: GoogleSignInExchange,
    auth_service: AuthServiceDep,
    merchant_service: MerchantServiceDep,
):
    access_token, refresh_token = await auth_service.exchange_google_code(
        exchange_payload, merchant_service, security
    )
    return SuccessResponse(data=_token(access_token, refresh_token))


@router.post(
    "/auth/google/complete",
    status_code=201,
    response_model=SuccessResponse[Token],
    description=(
        "Finish a new google sign up with the business name, using the signup_token "
        "from the google redirect, then sign in"
    ),
    dependencies=[write_limiter],
)
async def complete_google_sign_up(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    sign_up_payload: GoogleSignUpComplete,
    auth_service: AuthServiceDep,
):
    access_token, refresh_token = await auth_service.complete_google_sign_up(
        sign_up_payload, security, uow
    )
    return SuccessResponse(data=_token(access_token, refresh_token))
