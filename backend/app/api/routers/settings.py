from fastapi import APIRouter

from app.api.schemas.response import SuccessResponse
from app.api.schemas.settings import SettingsResponse, SettingsUpdate
from app.api.schemas.webhooks import WebhookSettingsResponse
from app.deps import (
    CurrentMerchant,
    SettingsServiceDep,
    UnitOfWorkRepo,
    WebhookServiceDep,
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
        "preferences after onboarding. Omitted fields are unchanged"
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


@router.get(
    "/settings/webhook",
    status_code=200,
    response_model=SuccessResponse[WebhookSettingsResponse],
    description=(
        "The merchant's Paystack webhook url with setup steps (created on first view), and "
        "whether it is delivering. Optional: without it, disputes are polled from Paystack"
    ),
    dependencies=[read_limiter],
)
async def get_webhook_settings(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    webhook_service: WebhookServiceDep,
):
    webhook: WebhookSettingsResponse = await webhook_service.get_settings(curr_merchant, uow)
    return SuccessResponse(data=webhook)


@router.post(
    "/settings/webhook/rotate",
    status_code=200,
    response_model=SuccessResponse[WebhookSettingsResponse],
    description=(
        "Issue a new webhook url; the old one stops working at once, so update it on Paystack"
    ),
    dependencies=[write_limiter],
)
async def rotate_webhook(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    webhook_service: WebhookServiceDep,
):
    webhook: WebhookSettingsResponse = await webhook_service.rotate(curr_merchant, uow)
    return SuccessResponse(data=webhook)
