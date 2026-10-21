from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError

from app.api.repo.trust import SyncTrustRepository
from app.api.services.ai_streams import publish_ai_job_sync
from app.database.session import sync_redis_client, sync_session
from app.worker.celery_app import celery_app
from app.worker.services.dispute_alerts import publish
from app.worker.services.trust import TrustOutcome, recompute_trust_profile
from app.worker.tasks.base import BaseTaskWithRetry

SCHEDULED: str = "scheduled"
# a burst of events (a sync matching dozens of payments) becomes one recomputation: each
# is queued this many seconds out, and a run finding a newer computation skips
DEBOUNCE_SECONDS: int = 5
TRUST_PRIORITY: int = 3


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def recompute_trust(self, merchant_id: str, reason: str, requested_at: str | None = None):
    """Recompute one merchant's trust profile. Skipped when a computation that started
    after this was requested already ran"""
    try:
        with sync_session() as session:
            if requested_at:
                profile_time = SyncTrustRepository(session).last_computed_at(UUID(merchant_id))
                if profile_time and profile_time >= datetime.fromisoformat(requested_at):
                    return
            outcome: TrustOutcome = recompute_trust_profile(session, UUID(merchant_id), reason)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Trust recomputation failed for merchant {merchant_id}: {error}",
            merchant_id=merchant_id,
            error=exc.__class__.__name__,
        )
        if isinstance(exc, OperationalError) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc
        raise Reject(exc, requeue=False) from exc

    _send_ai_jobs(merchant_id, outcome)
    if outcome.changed:
        publish(
            merchant_id,
            "trust.updated",
            {
                "state": outcome.state.value,
                "changed": outcome.state != outcome.previous_state,
                "previous_state": outcome.previous_state.value if outcome.previous_state else None,
                "reason": reason,
            },
        )


def _send_ai_jobs(merchant_id: str, outcome: TrustOutcome):
    """The explanation and state change summary; best effort, the profile is saved"""
    for job in outcome.ai_jobs:
        try:
            publish_ai_job_sync(sync_redis_client, job.event, job.payload, job.job_id)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "{event} could not be sent for merchant {merchant_id}",
                event=job.event,
                merchant_id=merchant_id,
            )


@celery_app.task
def schedule_trust_recomputes() -> int:
    """Daily (celery beat): every merchant, so the 30 and 90 day windows move on even
    without events"""
    with sync_session() as session:
        merchant_ids: list[UUID] = SyncTrustRepository(session).active_merchants()

    for merchant_id in merchant_ids:
        recompute_trust.apply_async(
            kwargs={"merchant_id": str(merchant_id), "reason": SCHEDULED},
            priority=TRUST_PRIORITY,
        )
    sentry_logger.info("Scheduled trust recomputes for {count} merchants", count=len(merchant_ids))
    return len(merchant_ids)


def request_trust_update_sync(merchant_id: UUID | str, reason: str):
    """For worker code: queue a recomputation after an event that moves a signal. Never
    raises; the daily run catches up on a lost one"""
    try:
        recompute_trust.apply_async(
            kwargs={
                "merchant_id": str(merchant_id),
                "reason": reason,
                "requested_at": datetime.now(UTC).isoformat(),
            },
            countdown=DEBOUNCE_SECONDS,
            priority=TRUST_PRIORITY,
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Trust update could not be queued for merchant {merchant_id}",
            merchant_id=str(merchant_id),
        )
