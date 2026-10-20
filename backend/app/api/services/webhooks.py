"""The optional paystack webhook.

Each merchant gets their own url, /webhooks/paystack/{token}. The token only says whose
delivery it is, so the right secret key verifies the signature (x-paystack-signature, an
HMAC-SHA512 of the raw body). A verified delivery is stored and acknowledged at once; a
celery task processes it. Paystack retries until it gets a 200, so a repeated body is
recognised and not processed twice.
"""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from starlette.concurrency import run_in_threadpool

from app.api.models.merchants import Merchant
from app.api.repo.merchants import MerchantRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.repo.webhook_events import WebhookEventRepository
from app.api.schemas.webhooks import WebhookSettingsResponse
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ServerError, WebhookSignatureError
from app.core.security import Security
from app.worker.tasks.webhooks import process_webhook_event

SETTINGS = get_settings()

TOKEN_PREFIX: str = "wh_"
# processed; every other event is acknowledged and dropped
HANDLED_EVENTS: tuple[str, ...] = (
    "charge.dispute.create",
    "charge.dispute.remind",
    "charge.dispute.resolve",
    "charge.success",
)
# goes ahead of syncs (6 and 4): a new dispute has a deadline
WEBHOOK_PRIORITY: int = 7


def webhook_url(token: str) -> str:
    return f"{SETTINGS.BACKEND_URL.rstrip('/')}{SETTINGS.API_PREFIX}/webhooks/paystack/{token}"


def is_active(merchant: Merchant, now: datetime | None = None) -> bool:
    if not merchant.webhook_last_received_at:
        return False
    now = now or datetime.now(UTC)
    return now - merchant.webhook_last_received_at < timedelta(hours=SETTINGS.WEBHOOK_ACTIVE_HOURS)


def signature_matches(secret_key: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected: str = hmac.new(secret_key.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


class WebhookService:
    def __init__(self, security: Security):
        self._security = security

    # ------------------------------ settings ------------------------------ #

    async def _save_token(self, merchant: Merchant, uow: UnitOfWorkRepository) -> Merchant:
        merchant.webhook_token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        merchant.updated_at = datetime.now(UTC)
        try:
            uow.repo(MerchantRepository).add(model=merchant)
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Webhook token could not be saved for merchant {merchant_id}",
                merchant_id=str(merchant.id),
            )
            raise ServerError() from exc
        return merchant

    @staticmethod
    def _response(merchant: Merchant) -> WebhookSettingsResponse:
        url: str = webhook_url(merchant.webhook_token)
        return WebhookSettingsResponse(
            url=url,
            active=is_active(merchant),
            last_received_at=merchant.webhook_last_received_at,
            events=list(HANDLED_EVENTS),
            setup_steps=[
                "Open your Paystack dashboard: Settings > API Keys & Webhooks.",
                "Use the mode (test or live) of the secret key you connected.",
                f"Paste {url} as the Webhook URL and save.",
                "Skip this if you already use a webhook for another system: disputes are "
                "then checked on Paystack regularly instead.",
            ],
        )

    async def get_settings(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> WebhookSettingsResponse:
        """The merchant's webhook url, created on first view"""
        if not curr_merchant.webhook_token:
            curr_merchant = await self._save_token(curr_merchant, uow)
        return self._response(curr_merchant)

    async def rotate(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> WebhookSettingsResponse:
        """A new url; the old one stops working at once"""
        merchant: Merchant = await self._save_token(curr_merchant, uow)
        sentry_logger.info(
            "Merchant {merchant_id} rotated their webhook url", merchant_id=str(merchant.id)
        )
        return self._response(merchant)

    # ------------------------------ deliveries ------------------------------ #

    async def receive(
        self, token: str, body: bytes, signature: str | None, uow: UnitOfWorkRepository
    ) -> None:
        """Verify, store and queue one delivery. 404 for an unknown url, 401 for a bad
        signature; everything else is acknowledged"""
        merchant: Merchant | None = await uow.repo(MerchantRepository).get_record(
            webhook_token=token
        )
        if not merchant or not merchant.is_active or not merchant.paystack_secret_key:
            raise NotFoundError("Webhook")

        secret_key: str = await self._security.decrypt_secret_key(merchant.paystack_secret_key)
        if not signature_matches(secret_key, body, signature):
            sentry_logger.warning(
                "Webhook with a bad signature for merchant {merchant_id}",
                merchant_id=str(merchant.id),
            )
            raise WebhookSignatureError()

        now: datetime = datetime.now(UTC)
        events = uow.repo(WebhookEventRepository)

        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        event: str | None = payload.get("event") if isinstance(payload, dict) else None

        try:
            await events.stamp_received(merchant.id, now)
            queued: tuple[UUID, bool] | None = None
            if event in HANDLED_EVENTS and isinstance(payload.get("data"), dict):
                queued = await events.record(
                    merchant.id, event, hashlib.sha256(body).hexdigest(), payload, now
                )
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Webhook could not be stored for merchant {merchant_id}",
                merchant_id=str(merchant.id),
            )
            # paystack retries, and a retry of an unprocessed delivery is queued again
            raise ServerError() from exc

        if not queued:
            sentry_logger.info(
                "Webhook {event} for merchant {merchant_id} acknowledged, not handled",
                event=str(event),
                merchant_id=str(merchant.id),
            )
            return

        event_id, pending = queued
        if not pending:
            return  # a retry of a delivery already processed

        try:
            await run_in_threadpool(
                process_webhook_event.apply_async,
                kwargs={"event_id": str(event_id)},
                priority=WEBHOOK_PRIORITY,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Webhook {event_id} could not be queued", event_id=str(event_id))
            raise ServerError() from exc

        sentry_logger.info(
            "Webhook {event} for merchant {merchant_id} queued as {event_id}",
            event=event,
            merchant_id=str(merchant.id),
            event_id=str(event_id),
        )
