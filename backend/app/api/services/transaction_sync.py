from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ServerError
from app.worker.tasks.transaction_sync import (
    INITIAL_SYNC_PRIORITY,
    RESYNC_PRIORITY,
    sync_transactions,
)


async def enqueue_transaction_sync(merchant_id: UUID, initial: bool):
    """Queue a transaction sync: initial pulls the last 30 days for onboarding, otherwise
    it runs from the merchant's last sync"""
    try:
        # publishing talks to the broker over a blocking connection
        await run_in_threadpool(
            sync_transactions.apply_async,
            kwargs={"merchant_id": str(merchant_id), "initial": initial},
            priority=INITIAL_SYNC_PRIORITY if initial else RESYNC_PRIORITY,
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Error occured while queueing transaction sync for merchant {merchant_id}",
            merchant_id=str(merchant_id),
        )
        raise ServerError() from exc
