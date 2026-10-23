from fastapi import APIRouter

from app.api.routers import (
    admin,
    admin_merchants,
    ai_memory,
    auth,
    customers,
    dashboard,
    disputes,
    events,
    fulfillments,
    onboarding,
    orders,
    paystack,
    reconciliation,
    settings,
    transactions,
    trust,
    uploads,
    webhooks,
)
from app.core.config import get_settings

SETTINGS = get_settings()

router = APIRouter(prefix=SETTINGS.API_PREFIX)
router.include_router(auth.router, tags=["Auth"])
router.include_router(paystack.router, tags=["Paystack"])
router.include_router(onboarding.router, tags=["Onboarding"])
router.include_router(settings.router, tags=["Settings"])
router.include_router(customers.router, tags=["Customers"])
router.include_router(orders.router, tags=["Orders"])
router.include_router(transactions.router, tags=["Transactions"])
router.include_router(uploads.router, tags=["Uploads"])
router.include_router(fulfillments.router, tags=["Fulfillments"])
router.include_router(reconciliation.router, tags=["Reconciliation"])
router.include_router(events.router, tags=["Events"])
router.include_router(webhooks.router, tags=["Webhooks"])
router.include_router(disputes.router, tags=["Disputes"])
router.include_router(trust.router, tags=["TrustLayer"])
router.include_router(dashboard.router, tags=["Dashboard"])
router.include_router(admin.router, tags=["Admin"])
router.include_router(admin_merchants.router, tags=["Admin"])
router.include_router(ai_memory.router, tags=["AI Memory"])
