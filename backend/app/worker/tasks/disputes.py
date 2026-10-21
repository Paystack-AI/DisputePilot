"""Dispute polling and the deadline watcher (celery beat).

Polling covers merchants without a working webhook: one whose webhook delivered in the last
WEBHOOK_ACTIVE_HOURS (settings) is skipped, since disputes reach us from it already. The deadline
watcher reads only our own records, so it runs for every merchant.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError

from app.api.clients.paystack import PaystackClient, PaystackError
from app.api.models.merchants import Merchant
from app.api.repo.disputes import SyncDisputeRepository
from app.core.config import get_settings
from app.core.security import Security
from app.database.session import sync_session
from app.worker.celery_app import celery_app
from app.worker.services.dispute_alerts import announce, announce_deadline, hours_left
from app.worker.services.disputes import DisputeIntake, DisputeIntakeService
from app.worker.tasks.base import BaseTaskWithRetry
from app.worker.tasks.transaction_sync import _http_client
from app.worker.tasks.webhooks import _dispute_trust

SECURITY = Security()
SETTINGS = get_settings()

AWAITING_MERCHANT: str = "awaiting-merchant-feedback"
PER_PAGE: int = 50
MAX_PAGES: int = 20
# warnings sent as the deadline nears, largest first
DEADLINE_WARNING_HOURS: tuple[int, ...] = (8, 4)
DISPUTE_POLL_PRIORITY: int = 6


def _is_retryable(exc: Exception) -> bool:
    return (isinstance(exc, PaystackError) and exc.retryable) or isinstance(exc, OperationalError)


@celery_app.task
def schedule_dispute_polls():
    """Every 5 minutes: one poll per connected merchant whose webhook is quiet"""
    quiet_since: datetime = datetime.now(UTC) - timedelta(hours=SETTINGS.WEBHOOK_ACTIVE_HOURS)
    with sync_session() as session:
        merchant_ids: list[UUID] = SyncDisputeRepository(session).merchants_to_poll(quiet_since)

    for merchant_id in merchant_ids:
        poll_disputes.apply_async(
            kwargs={"merchant_id": str(merchant_id)}, priority=DISPUTE_POLL_PRIORITY
        )

    sentry_logger.info("Scheduled dispute polls for {count} merchants", count=len(merchant_ids))


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def poll_disputes(self, merchant_id: str) -> int:
    """Disputes awaiting the merchant (new ones included), then each of our open ones that
    left that list, to catch what paystack changed. Returns how many were taken in"""
    taken: int = 0
    try:
        with sync_session() as session:
            merchant: Merchant | None = session.get(Merchant, UUID(merchant_id))
            if not merchant or not merchant.is_active or not merchant.paystack_secret_key:
                return 0

            client = PaystackClient(
                SECURITY.decrypt_secret_key_sync(merchant.paystack_secret_key), _http_client()
            )
            intake_service = DisputeIntakeService(session, merchant, client)
            seen: set[int] = set()

            def take(data: dict):
                nonlocal taken
                intake: DisputeIntake = intake_service.upsert(data)
                seen.add(int(data["id"]))
                # one commit per dispute: an alert never goes out for an unsaved record
                session.commit()
                announce(session, merchant, intake)
                _dispute_trust(merchant.id, intake)
                taken += 1

            for page in range(1, MAX_PAGES + 1):
                body: dict = client.list_disputes(
                    per_page=PER_PAGE, page=page, status=AWAITING_MERCHANT
                )
                disputes: list = body.get("data") or []
                for data in disputes:
                    if isinstance(data, dict) and data.get("id") is not None:
                        take(data)
                page_count: int = int((body.get("meta") or {}).get("pageCount") or 1)
                if not disputes or page >= page_count:
                    break

            # open on our side but no longer awaiting the merchant: resolved, or with the bank
            for paystack_id in SyncDisputeRepository(session).open_paystack_ids(merchant.id):
                if paystack_id in seen:
                    continue
                data = client.fetch_dispute(paystack_id).get("data")
                if isinstance(data, dict):
                    take(data)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Dispute poll failed for merchant {merchant_id}: {error}",
            merchant_id=merchant_id,
            error=exc.__class__.__name__,
        )
        if _is_retryable(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info(
        "Dispute poll took in {taken} disputes for merchant {merchant_id}",
        taken=taken,
        merchant_id=merchant_id,
    )
    return taken


def _warning_due(hours: float, last_sent: int | None) -> int | None:
    """The threshold to warn at now, if it has not gone out yet"""
    due: list[int] = [threshold for threshold in DEADLINE_WARNING_HOURS if hours <= threshold]
    if not due:
        return None
    threshold: int = min(due)
    if last_sent is not None and last_sent <= threshold:
        return None
    return threshold


@celery_app.task
def watch_deadlines() -> int:
    """Every 15 minutes: the 8 and 4 hour warnings for disputes still waiting on the
    merchant, each sent once. Returns how many went out"""
    now: datetime = datetime.now(UTC)
    sent: int = 0

    with sync_session() as session:
        rows = SyncDisputeRepository(session).awaiting_response(
            now, now + timedelta(hours=max(DEADLINE_WARNING_HOURS))
        )
        due: list = []
        for dispute, merchant in rows:
            remaining: float = (dispute.due_at - now).total_seconds() / 3600
            threshold: int | None = _warning_due(remaining, dispute.last_deadline_warning_hours)
            if threshold is not None:
                dispute.last_deadline_warning_hours = threshold
                due.append((dispute, merchant))
        # recorded first: a crash afterwards loses a warning rather than repeating it
        session.commit()

        for dispute, merchant in due:
            announce_deadline(
                session, merchant, dispute, dispute.paystack_reference, hours_left(dispute, now)
            )
            sent += 1

    if sent:
        sentry_logger.info("Sent {sent} dispute deadline warnings", sent=sent)
    return sent
