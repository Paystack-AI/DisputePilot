from typing import Annotated
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models.merchants import Merchant
from app.api.repo.merchants import MerchantRepository
from app.api.repo.redis import RedisRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.services.auth import AuthService
from app.api.services.customer_ledger import CustomerLedgerService
from app.api.services.merchants import MerchantService
from app.api.services.onboarding import OnboardingService
from app.api.services.order_management import OrderManagementService
from app.api.services.paystack import PaystackService
from app.api.services.settings import SettingsService
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import Security
from app.database.session import get_session
from app.limiter import _limiter_handler

SETTINGS = get_settings()

# Auth bearer
bearer = HTTPBearer(auto_error=False)

# ------------------- DB dependency ------------------------------ #

DBSession = Annotated[AsyncSession, Depends(get_session)]


# ------------------- Redis dependency ------------------------------ #
async def get_redis_client(request: Request) -> Redis:
    redis_client: Redis = request.app.state.redis
    return redis_client


RedisDep = Annotated[Redis, Depends(get_redis_client)]


# ------------------- Paystack http dependency ------------------------------ #
async def get_paystack_http(request: Request) -> AsyncClient:
    """Connection pool shared by every merchant's paystack client"""
    paystack_http: AsyncClient = request.app.state.paystack_http
    return paystack_http


PaystackHttp = Annotated[AsyncClient, Depends(get_paystack_http)]


# ------------------- Security dependency ------------------------------ #
async def get_security() -> Security:
    return Security()


SecurityDep = Annotated[Security, Depends(get_security)]

#  ------------------- Repo dependency ----------------------------- #


async def get_merchant_repo(session: DBSession) -> MerchantRepository:
    return MerchantRepository(async_session=session)


async def get_redis_repo(redis: RedisDep) -> RedisRepository:
    return RedisRepository(async_redis=redis)


async def get_unit_of_work(session: DBSession) -> UnitOfWorkRepository:
    return UnitOfWorkRepository(async_session=session)


MerchantRepo = Annotated[MerchantRepository, Depends(get_merchant_repo)]
RedisRepo = Annotated[RedisRepository, Depends(get_redis_repo)]
UnitOfWorkRepo = Annotated[UnitOfWorkRepository, Depends(get_unit_of_work)]

#  -------------------- Service dependency ---------------------------- #


async def get_merchant_service(merchant_repo: MerchantRepo) -> MerchantService:
    return MerchantService(merchant_repo=merchant_repo)


async def get_auth_service(redis_repo: RedisRepo) -> AuthService:
    return AuthService(redis_repo=redis_repo)


async def get_paystack_service(paystack_http: PaystackHttp) -> PaystackService:
    return PaystackService(paystack_http=paystack_http)


async def get_settings_service() -> SettingsService:
    return SettingsService()


async def get_onboarding_service() -> OnboardingService:
    return OnboardingService()


async def get_customer_ledger_service() -> CustomerLedgerService:
    return CustomerLedgerService()


async def get_order_management_service() -> OrderManagementService:
    return OrderManagementService()


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
MerchantServiceDep = Annotated[MerchantService, Depends(get_merchant_service)]
PaystackServiceDep = Annotated[PaystackService, Depends(get_paystack_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
OnboardingServiceDep = Annotated[OnboardingService, Depends(get_onboarding_service)]
CustomerLedgerServiceDep = Annotated[CustomerLedgerService, Depends(get_customer_ledger_service)]
OrderManagementServiceDep = Annotated[OrderManagementService, Depends(get_order_management_service)]

# ------------------------ Auth dependency ---------------------------- #


async def _decode_credentials(
    security: SecurityDep,
    auth_service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> dict:
    """Returns the claims of a validated, non-blacklisted access token."""
    if not credentials:
        sentry_logger.error("Merchant not authenticated")
        raise AuthenticationError()

    token: str | None = credentials.credentials
    key: str = SETTINGS.ACCESS_TOKEN_SECRET_KEY

    # raises TokenExpiredError for expired tokens
    payload: dict = await security.decode_token(token, key)

    if not payload:
        sentry_logger.error("Merchant not authenticated")
        raise AuthenticationError()

    await auth_service.verify_access_token(payload)

    return payload


AccessTokenClaims = Annotated[dict, Depends(_decode_credentials)]


async def get_current_merchant(
    merchant_service: MerchantServiceDep, access_token_claims: AccessTokenClaims
) -> Merchant:
    merchant_id: str = access_token_claims["sub"]

    merchant: Merchant | None = await merchant_service._get_merchant(id=UUID(merchant_id))

    if not merchant or not merchant.is_verified or not merchant.is_active:
        sentry_logger.error(
            "Merchant {merchant_id} not found or not active", merchant_id=merchant_id
        )
        raise AuthenticationError()

    return merchant


CurrentMerchant = Annotated[Merchant, Depends(get_current_merchant)]


# ------------------------ Limiter -------------------------------- #
write_limiter = Depends(
    _limiter_handler(key=SETTINGS.WRITE_LIMIT_KEY, limit=10, unit="minutes", multiplier=15)
)

read_limiter = Depends(
    _limiter_handler(key=SETTINGS.READ_LIMIT_KEY, limit=10, unit="minutes", multiplier=1)
)
