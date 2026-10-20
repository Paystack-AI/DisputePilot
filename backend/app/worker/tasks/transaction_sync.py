from datetime import UTC, datetime
from uuid import UUID

import httpx
import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackClient, PaystackError, create_http_client
from app.api.models.merchants import Merchant
from app.api.services.events import publish_event_sync
from app.api.services.reconciliation_engine import MatchOutcome, auto_match_after_sync
from app.core.security import Security
from app.database.session import sync_redis_client, sync_session
from app.worker.celery_app import celery_app
from app.worker.services.transaction_sync import (
    TransactionSync,
    mark_initial_sync_failed,
    merchants_due_for_sync,
)
from app.worker.tasks.base import BaseTaskWithRetry

# below auth emails (8): nobody waits on the daily run; the initial sync drives the
# onboarding progress bar, so it goes ahead of it
INITIAL_SYNC_PRIORITY: int = 6
RESYNC_PRIORITY: int = 4

SECURITY = Security()

# one connection pool per worker process, shared by every merchant's sync
_paystack_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _paystack_http
    if _paystack_http is None:
        _paystack_http = create_http_client()
    return _paystack_http


def _is_retryable(exc: Exception) -> bool:
    # paystack down / rate limiting, or the database briefly unreachable
    return (isinstance(exc, PaystackError) and exc.retryable) or isinstance(exc, OperationalError)


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def sync_transactions(self, merchant_id: str, initial: bool = False):
    """Fetch the merchant's transactions since their last sync (the last 30 days when
    initial, i.e. onboarding). Retries restart the window from the first page"""
    try:
        with sync_session() as session:
            merchant: Merchant | None = session.get(Merchant, UUID(merchant_id))

            if not merchant or not merchant.is_active or not merchant.paystack_secret_key:
                sentry_logger.info(
                    "Transaction sync skipped for merchant {merchant_id}: not connected",
                    merchant_id=merchant_id,
                )
                return

            client = PaystackClient(
                SECURITY.decrypt_secret_key_sync(merchant.paystack_secret_key), _http_client()
            )
            stored: int = TransactionSync(session, client, merchant).run(
                initial=initial, started_at=datetime.now(UTC)
            )
            outcome: MatchOutcome = _auto_match(session, merchant.id)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Transaction sync failed for merchant {merchant_id}: {error}",
            merchant_id=merchant_id,
            error=exc.__class__.__name__,
        )

        if _is_retryable(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc

        # out of retries, or a failure retrying can't fix (e.g. the key was revoked)
        if initial:
            with sync_session() as session:
                mark_initial_sync_failed(session, UUID(merchant_id))
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info(
        "Transaction sync stored {stored} transactions for merchant {merchant_id}",
        stored=stored,
        merchant_id=merchant_id,
    )
    _publish_sync_events(merchant_id, stored, outcome)


def _auto_match(session: Session, merchant_id: UUID) -> MatchOutcome:
    """Reconcile what the sync brought in. The transactions are already committed, so a
    failure here only skips matching until the next sync"""
    try:
        outcome: MatchOutcome = auto_match_after_sync(session, merchant_id)
        session.commit()
    except Exception as exc:
        session.rollback()
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Automatic matching failed for merchant {merchant_id}", merchant_id=str(merchant_id)
        )
        return MatchOutcome()

    if outcome.changed:
        sentry_logger.info(
            "Automatic matching for merchant {merchant_id}: {matched} matched, {suggested} "
            "suggested, {flagged} flagged",
            merchant_id=str(merchant_id),
            **outcome.as_dict(),
        )
    return outcome


def _publish_sync_events(merchant_id: str, stored: int, outcome: MatchOutcome):
    """Tell the merchant's open dashboards; live updates are best effort"""
    try:
        publish_event_sync(
            sync_redis_client, merchant_id, "transaction.synced", {"count_new": stored}
        )
        if outcome.changed:
            publish_event_sync(
                sync_redis_client,
                merchant_id,
                "reconciliation.updated",
                {"session_id": None, "automatic": outcome.as_dict()},
            )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Sync events could not be published for merchant {merchant_id}",
            merchant_id=merchant_id,
        )


@celery_app.task
def schedule_transaction_syncs():
    """Daily (celery beat): one sync per connected merchant, each from its last sync"""
    with sync_session() as session:
        merchant_ids: list[UUID] = merchants_due_for_sync(session)

    for merchant_id in merchant_ids:
        sync_transactions.apply_async(
            kwargs={"merchant_id": str(merchant_id)}, priority=RESYNC_PRIORITY
        )

    sentry_logger.info("Scheduled transaction syncs for {count} merchants", count=len(merchant_ids))
