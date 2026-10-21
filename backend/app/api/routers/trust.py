from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.schemas.response import SuccessResponse
from app.api.schemas.trust import (
    PublicTrustBadge,
    PublicTrustPage,
    TrustHistory,
    TrustHistoryQuery,
    TrustProfileResponse,
    TrustSettingsUpdate,
    TrustSignalsBreakdown,
)
from app.api.services.trust import PUBLIC_CACHE_SECONDS
from app.deps import (
    CurrentMerchant,
    TrustServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()

# public pages are the same for everyone, so any cache may keep them a few minutes
PUBLIC_CACHE: str = f"public, max-age={PUBLIC_CACHE_SECONDS}, stale-while-revalidate=60"


@router.get(
    "/trust/profile",
    status_code=200,
    response_model=SuccessResponse[TrustProfileResponse],
    description=(
        "The merchant's trust state, internal score (merchant only), signals with their "
        "readings, the public switches and the public url. The first visit queues the first "
        "computation"
    ),
    dependencies=[read_limiter],
)
async def get_trust_profile(
    uow: UnitOfWorkRepo, curr_merchant: CurrentMerchant, trust_service: TrustServiceDep
):
    return SuccessResponse(data=await trust_service.get_profile(curr_merchant, uow))


@router.put(
    "/trust/profile/settings",
    status_code=200,
    response_model=SuccessResponse[TrustProfileResponse],
    description="Turn the public trust page and the embeddable badge on or off",
    dependencies=[write_limiter],
)
async def update_trust_settings(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: TrustSettingsUpdate,
    trust_service: TrustServiceDep,
):
    profile: TrustProfileResponse = await trust_service.update_settings(curr_merchant, payload, uow)
    return SuccessResponse(data=profile)


@router.get(
    "/trust/signals",
    status_code=200,
    response_model=SuccessResponse[TrustSignalsBreakdown],
    description=(
        "Each signal against the thresholds: what is contributing, and what is keeping the "
        "merchant from the next state, with an action for each"
    ),
    dependencies=[read_limiter],
)
async def get_trust_signals(
    uow: UnitOfWorkRepo, curr_merchant: CurrentMerchant, trust_service: TrustServiceDep
):
    return SuccessResponse(data=await trust_service.signals(curr_merchant, uow))


@router.get(
    "/trust/history",
    status_code=200,
    response_model=SuccessResponse[TrustHistory],
    description=(
        "Snapshots (taken whenever the state or the internal score changed) over 7, 30 or 90 "
        "days, and the state changes among them"
    ),
    dependencies=[read_limiter],
)
async def get_trust_history(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    trust_service: TrustServiceDep,
    query: Annotated[TrustHistoryQuery, Query()],
):
    return SuccessResponse(data=await trust_service.history(curr_merchant, query.days, uow))


@router.get(
    "/public/trust/{token}",
    status_code=200,
    response_model=SuccessResponse[PublicTrustPage],
    description=(
        "The public trust page: merchant name, state and a worded summary. No score, rates, "
        "customer or dispute data. 404 when the page is off, the state is review, or the "
        "token is unknown (the same response for all three)"
    ),
    dependencies=[read_limiter],
)
async def public_trust_page(
    token: str, response: Response, uow: UnitOfWorkRepo, trust_service: TrustServiceDep
):
    page: PublicTrustPage = await trust_service.public_page(token, uow)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return SuccessResponse(data=page)


@router.get(
    "/public/trust/{token}/badge",
    status_code=200,
    response_model=SuccessResponse[PublicTrustBadge],
    description="Embeddable badge data: state, merchant name and verified since. 404 when off",
    dependencies=[read_limiter],
)
async def public_trust_badge(
    token: str, response: Response, uow: UnitOfWorkRepo, trust_service: TrustServiceDep
):
    badge: PublicTrustBadge = await trust_service.public_badge(token, uow)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return SuccessResponse(data=badge)
