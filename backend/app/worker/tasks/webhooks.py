from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackClient, PaystackError
from app.api.models.merchants import Merchant
from app.api.models.webhook_events import WebhookEvent
from app.api.repo.webhook_events import SyncWebhookEventRepository
from app.api.services.reconciliation_engine import MatchOutcome, auto_match_after_sync
from app.core.security import Security
from app.database.session import sync_session
from app.worker.celery_app import celery_app
from app.worker.services.dispute_alerts import (
    announce,
    announce_deadline,
    announce_update,
    hours_left,
    publish,
)
from app.worker.services.disputes import DisputeIntake, DisputeIntakeService
from app.worker.services.transaction_sync import TransactionSync
from app.worker.tasks.base import BaseTaskWithRetry
from app.worker.tasks.transaction_sync import _http_client

SECURITY = Security()

DISPUTE_EVENTS: tuple[str, ...] = (
    "charge.dispute.create",
    "charge.dispute.remind",
    "charge.dispute.resolve",
)


def _is_retryable(exc: Exception) -> bool:
    return (isinstance(exc, PaystackError) and exc.retryable) or isinstance(exc, OperationalError)


def _client(merchant: Merchant) -> PaystackClient | None:
    if not merchant.paystack_secret_key:
        return None
    return PaystackClient(
        SECURITY.decrypt_secret_key_sync(merchant.paystack_secret_key), _http_client()
    )


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def process_webhook_event(self, event_id: str):
    """Acts on one stored paystack webhook delivery: a dispute opened, reminded or resolved,
    or a successful payment. Runs once per delivery; a retry after it finished does nothing"""
    try:
        with sync_session() as session:
            events = SyncWebhookEventRepository(session)
            event: WebhookEvent | None = events.get_for_update(UUID(event_id))
            if not event or event.processed_at:
                return

            merchant: Merchant | None = session.get(Merchant, event.merchant_id)
            name: str = event.event
            data: dict = (event.payload or {}).get("data") or {}

            if not merchant or not merchant.is_active:
                events.mark_processed(event, datetime.now(UTC))
                session.commit()
                return

            if name == "charge.success":
                stored: int = TransactionSync(session, None, merchant).store([data])
                outcome: MatchOutcome = auto_match_after_sync(session, merchant.id)
                events.mark_processed(event, datetime.now(UTC))
                session.commit()
                _after_payment(str(merchant.id), stored, outcome)
            elif name in DISPUTE_EVENTS:
                intake: DisputeIntake = DisputeIntakeService(
                    session, merchant, _client(merchant)
                ).upsert(data)
                events.mark_processed(event, datetime.now(UTC))
                session.commit()
                _after_dispute(session, merchant, name, intake)
            else:
                events.mark_processed(event, datetime.now(UTC))
                session.commit()
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Webhook {event_id} failed: {error}", event_id=event_id, error=exc.__class__.__name__
        )

        if _is_retryable(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc

        with sync_session() as session:
            SyncWebhookEventRepository(session).mark_failed(UUID(event_id), repr(exc))
            session.commit()
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info("Webhook {event_id} processed", event_id=event_id)


def _after_payment(merchant_id: str, stored: int, outcome: MatchOutcome):
    publish(merchant_id, "transaction.synced", {"count_new": stored})
    if outcome.changed:
        publish(
            merchant_id,
            "reconciliation.updated",
            {"session_id": None, "automatic": outcome.as_dict()},
        )


def _after_dispute(session: Session, merchant: Merchant, name: str, intake: DisputeIntake):
    if name == "charge.dispute.remind":
        # paystack's own reminder, on top of the 8 and 4 hour warnings
        announce_deadline(
            session, merchant, intake.dispute, intake.reference, hours_left(intake.dispute)
        )
    elif name == "charge.dispute.resolve":
        announce_update(session, merchant, intake)
    else:
        announce(session, merchant, intake)
