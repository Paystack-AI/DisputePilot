from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from app.core.config import get_settings
from app.core.exceptions import PayloadTooLargeError
from app.deps import UnitOfWorkRepo, WebhookServiceDep

SETTINGS = get_settings()

router = APIRouter()


@router.post(
    "/webhooks/paystack/{token}",
    status_code=200,
    include_in_schema=False,
    description=(
        "Paystack webhook deliveries for one merchant. Verified with the merchant's secret "
        "key, stored and acknowledged; dispute events and successful payments are processed "
        "in the background. Not rate limited: Paystack retries until it gets a 200"
    ),
)
async def paystack_webhook(
    request: Request,
    token: str,
    uow: UnitOfWorkRepo,
    webhook_service: WebhookServiceDep,
    signature: Annotated[str | None, Header(alias="x-paystack-signature")] = None,
):
    declared: str | None = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > SETTINGS.WEBHOOK_MAX_BODY_BYTES:
        raise PayloadTooLargeError(SETTINGS.WEBHOOK_MAX_BODY_BYTES // 1_000_000)

    # the signature covers the exact bytes paystack sent, so the body is read raw
    body: bytes = await request.body()
    if len(body) > SETTINGS.WEBHOOK_MAX_BODY_BYTES:
        raise PayloadTooLargeError(SETTINGS.WEBHOOK_MAX_BODY_BYTES // 1_000_000)

    await webhook_service.receive(token, body, signature, uow)
    return Response(status_code=200)
