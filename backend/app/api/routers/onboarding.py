from fastapi import APIRouter

from app.api.schemas.onboarding import OnboardingResponse
from app.api.schemas.response import SuccessResponse
from app.api.schemas.settings import NotificationPreferences
from app.deps import (
    CurrentMerchant,
    OnboardingServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/onboarding",
    status_code=200,
    response_model=SuccessResponse[OnboardingResponse],
    description=(
        "Current onboarding step and initial sync progress. "
        "Used to resume onboarding after a login or a closed tab"
    ),
    dependencies=[read_limiter],
)
async def get_onboarding(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    onboarding_service: OnboardingServiceDep,
):
    # TODO: live sync progress will be pushed over SSE (GET /events), sending this
    # same payload as the first event so a reconnecting client is up to date
    onboarding: OnboardingResponse = await onboarding_service.get_onboarding(curr_merchant, uow)
    return SuccessResponse(data=onboarding)


@router.post(
    "/onboarding/notifications",
    status_code=200,
    response_model=SuccessResponse[OnboardingResponse],
    description=(
        "Step 2, after connecting Paystack: save notification preferences (an empty body "
        "keeps the defaults) and start the initial transaction sync"
    ),
    dependencies=[write_limiter],
)
async def configure_notifications(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    preferences: NotificationPreferences,
    onboarding_service: OnboardingServiceDep,
):
    onboarding: OnboardingResponse = await onboarding_service.configure_notifications(
        curr_merchant, preferences, uow
    )
    return SuccessResponse(data=onboarding)


@router.post(
    "/onboarding/first-reconciliation/skip",
    status_code=200,
    response_model=SuccessResponse[OnboardingResponse],
    description="Step 4: finish onboarding and do the first reconciliation later",
    dependencies=[write_limiter],
)
async def skip_first_reconciliation(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    onboarding_service: OnboardingServiceDep,
):
    onboarding: OnboardingResponse = await onboarding_service.skip_first_reconciliation(
        curr_merchant, uow
    )
    return SuccessResponse(data=onboarding)
