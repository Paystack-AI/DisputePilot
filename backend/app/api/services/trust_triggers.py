"""Events that move a trust signal queue a recomputation of the merchant's profile.

reconciliation_rate  <- payments synced or received, matches made, accepted or undone
fulfillment_rate     <- fulfillments logged or changed, orders resolved or cancelled
dispute_rate         <- disputes opened
dispute_win_rate     <- disputes resolved
avg_response_time    <- disputes submitted
evidence_readiness   <- any of the above (matches, fulfillments, photos)
"""

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.worker.tasks.trust import request_trust_update_sync

# reasons recorded on the snapshot
TRANSACTIONS_SYNCED: str = "transactions_synced"
PAYMENT_RECEIVED: str = "payment_received"
RECONCILIATION_UPDATED: str = "reconciliation_updated"
RECONCILIATION_COMPLETED: str = "reconciliation_completed"
FULFILLMENT_LOGGED: str = "fulfillment_logged"
ORDER_UPDATED: str = "order_updated"
DISPUTE_OPENED: str = "dispute_opened"
DISPUTE_SUBMITTED: str = "dispute_submitted"
DISPUTE_RESOLVED: str = "dispute_resolved"


async def request_trust_update(merchant_id: UUID | str, reason: str):
    """For the api, after the change is committed; publishing to the broker blocks"""
    await run_in_threadpool(request_trust_update_sync, merchant_id, reason)
