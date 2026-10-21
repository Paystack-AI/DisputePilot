from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.schemas.admin import (
    AdminLogin,
    AdminMerchantDetail,
    AdminMerchantListItem,
    AdminMerchantListQuery,
    AdminOverview,
    AdminResponse,
    AdminToken,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.core.config import get_settings
from app.deps import (
    AdminAccessTokenClaims,
    AdminAuthServiceDep,
    AdminServiceDep,
    CurrentAdmin,
    SecurityDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

SETTINGS = get_settings()

router = APIRouter(prefix="/admin")


@router.post(
    "/auth/login",
    status_code=200,
    response_model=SuccessResponse[AdminToken],
    description="Log in to a separate operator account created with app.scripts.create_admin",
    dependencies=[write_limiter],
)
async def admin_login(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    payload: AdminLogin,
    admin_auth_service: AdminAuthServiceDep,
):
    _, access_token = await admin_auth_service.login(payload, security, uow)
    return SuccessResponse(
        data=AdminToken(
            access_token=access_token,
            expires_in=SETTINGS.ACCESS_TOKEN_EXPIRE_TIME * 60,
        )
    )


@router.get(
    "/auth/me",
    status_code=200,
    response_model=SuccessResponse[AdminResponse],
    description="The logged-in operator account",
    dependencies=[read_limiter],
)
async def admin_me(current_admin: CurrentAdmin):
    return SuccessResponse(data=AdminResponse.model_validate(current_admin))


@router.post(
    "/auth/logout",
    status_code=204,
    description="End the admin session; its access token stops working immediately",
    dependencies=[write_limiter],
)
async def admin_logout(
    admin_claims: AdminAccessTokenClaims,
    admin_auth_service: AdminAuthServiceDep,
):
    await admin_auth_service.logout(admin_claims)


@router.get(
    "/overview",
    status_code=200,
    response_model=SuccessResponse[AdminOverview],
    description="Installation-wide counts: merchants, Paystack connections, transactions, "
    "disputes, orders, customers and trust states",
    dependencies=[read_limiter],
)
async def admin_overview(
    uow: UnitOfWorkRepo,
    current_admin: CurrentAdmin,
    admin_service: AdminServiceDep,
):
    return SuccessResponse(data=await admin_service.overview(uow))


@router.get(
    "/merchants",
    status_code=200,
    response_model=ListSuccessResponse[AdminMerchantListItem],
    description="Every merchant, newest first, with onboarding, Paystack, trust and "
    "transaction/dispute counts. search matches business name or email",
    dependencies=[read_limiter],
)
async def list_merchants(
    uow: UnitOfWorkRepo,
    current_admin: CurrentAdmin,
    query: Annotated[AdminMerchantListQuery, Query()],
    admin_service: AdminServiceDep,
):
    merchants, meta = await admin_service.list_merchants(query, uow)
    return ListSuccessResponse(data=merchants, meta=meta)


@router.get(
    "/merchants/{merchant_id}",
    status_code=200,
    response_model=SuccessResponse[AdminMerchantDetail],
    description="One merchant with Paystack/onboarding/settings state, trust profile and "
    "history, counts, and their recent transactions and disputes",
    dependencies=[read_limiter],
)
async def merchant_detail(
    merchant_id: UUID,
    uow: UnitOfWorkRepo,
    current_admin: CurrentAdmin,
    admin_service: AdminServiceDep,
):
    return SuccessResponse(data=await admin_service.merchant_detail(merchant_id, uow))
