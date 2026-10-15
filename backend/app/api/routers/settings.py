from fastapi import APIRouter

from app.api.schemas.response import SuccessResponse
from app.api.schemas.settings import SettingsResponse, SettingsUpdate
from app.deps import (
    CurrentMerchant,
    SettingsServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/settings",
    status_code=200,
    response_model=SuccessResponse[SettingsResponse],
    description="Get the merchant's settings",
    dependencies=[read_limiter],
)
async def get_settings(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    settings_service: SettingsServiceDep,
):
    settings: SettingsResponse = await settings_service.get_settings(curr_merchant, uow)
    return SuccessResponse(data=settings)


@router.patch(
    "/settings",
    status_code=200,
    response_model=SuccessResponse[SettingsResponse],
    description=(
        "Update any combination of the merchant's settings, including notification "
        "preferences after onboarding. Omitted fields are unchanged; "
        "notification_whatsapp set to null disables whatsapp alerts"
    ),
    dependencies=[write_limiter],
)
async def update_settings(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    update_payload: SettingsUpdate,
    settings_service: SettingsServiceDep,
):
    settings: SettingsResponse = await settings_service.update_settings(
        curr_merchant, update_payload, uow
    )
    return SuccessResponse(data=settings)
