"""Read-only views of one merchant's data for an admin, for demos.

Each route loads the merchant by id and calls the same service the merchant's own route
calls, so the admin sees exactly what the merchant sees, without the merchant's
credentials. Only GETs: nothing here can change a merchant's data.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.models.merchants import Merchant
from app.api.schemas.customers import (
    CustomerListQuery,
    CustomerResponse,
    CustomerSummary,
    LedgerEntry,
)
from app.api.schemas.dashboard import Dashboard, DashboardQuery
from app.api.schemas.disputes import (
    DisputeDetail,
    DisputeListQuery,
    DisputeStats,
    DisputeSummary,
)
from app.api.schemas.fulfillments import FulfillmentListQuery, FulfillmentResponse
from app.api.schemas.orders import OrderDetail, OrderListQuery, OrderResponse
from app.api.schemas.pagination import PageParams
from app.api.schemas.reconciliation import (
    ReconciliationSessionResponse,
    ReconciliationSummary,
    ReconciliationView,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.api.schemas.transactions import (
    TransactionDetail,
    TransactionListQuery,
    TransactionResponse,
)
from app.api.schemas.trust import (
    TrustActions,
    TrustHistory,
    TrustHistoryQuery,
    TrustProfileResponse,
    TrustSignalsBreakdown,
)
from app.deps import (
    AdminServiceDep,
    CurrentAdmin,
    CustomerLedgerServiceDep,
    DashboardServiceDep,
    DisputeServiceDep,
    FulfillmentLogServiceDep,
    MinioDep,
    OrderManagementServiceDep,
    ReconciliationServiceDep,
    TransactionServiceDep,
    TrustServiceDep,
    UnitOfWorkRepo,
    read_limiter,
)

router = APIRouter(prefix="/admin/merchants/{merchant_id}", dependencies=[read_limiter])


async def get_viewed_merchant(
    merchant_id: UUID,
    current_admin: CurrentAdmin,
    uow: UnitOfWorkRepo,
    admin_service: AdminServiceDep,
) -> Merchant:
    """The merchant being viewed; admins only. 404 for an unknown id"""
    return await admin_service.viewed_merchant(merchant_id, uow)


ViewedMerchant = Annotated[Merchant, Depends(get_viewed_merchant)]


# ------------------------------ dashboard ------------------------------ #


@router.get("/dashboard", response_model=SuccessResponse[Dashboard])
async def merchant_dashboard(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[DashboardQuery, Query()],
    service: DashboardServiceDep,
):
    return SuccessResponse(data=await service.dashboard(merchant, query, uow))


# ------------------------------ transactions ------------------------------ #


@router.get("/transactions", response_model=ListSuccessResponse[TransactionResponse])
async def merchant_transactions(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[TransactionListQuery, Query()],
    service: TransactionServiceDep,
):
    transactions, meta = await service.list_transactions(merchant, query, uow)
    return ListSuccessResponse(data=transactions, meta=meta)


@router.get("/transactions/{reference}", response_model=SuccessResponse[TransactionDetail])
async def merchant_transaction(
    merchant: ViewedMerchant, reference: str, uow: UnitOfWorkRepo, service: TransactionServiceDep
):
    return SuccessResponse(data=await service.get_transaction(merchant, reference, uow))


# ------------------------------ orders and customers ------------------------------ #


@router.get("/orders", response_model=ListSuccessResponse[OrderResponse])
async def merchant_orders(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[OrderListQuery, Query()],
    service: OrderManagementServiceDep,
):
    orders, meta = await service.list_orders(merchant, query, uow)
    return ListSuccessResponse(data=orders, meta=meta)


@router.get("/orders/{order_id}", response_model=SuccessResponse[OrderDetail])
async def merchant_order(
    merchant: ViewedMerchant,
    order_id: UUID,
    uow: UnitOfWorkRepo,
    service: OrderManagementServiceDep,
):
    return SuccessResponse(data=await service.get_order(merchant, order_id, uow))


@router.get("/customers", response_model=ListSuccessResponse[CustomerSummary])
async def merchant_customers(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[CustomerListQuery, Query()],
    service: CustomerLedgerServiceDep,
):
    customers, meta = await service.list_customers(merchant, query, uow)
    return ListSuccessResponse(data=customers, meta=meta)


@router.get("/customers/{customer_id}", response_model=SuccessResponse[CustomerResponse])
async def merchant_customer(
    merchant: ViewedMerchant,
    customer_id: UUID,
    uow: UnitOfWorkRepo,
    service: CustomerLedgerServiceDep,
):
    return SuccessResponse(data=await service.get_customer(merchant, customer_id, uow))


@router.get("/customers/{customer_id}/ledger", response_model=ListSuccessResponse[LedgerEntry])
async def merchant_customer_ledger(
    merchant: ViewedMerchant,
    customer_id: UUID,
    uow: UnitOfWorkRepo,
    params: Annotated[PageParams, Query()],
    service: CustomerLedgerServiceDep,
):
    entries, meta = await service.customer_ledger(merchant, customer_id, params, uow)
    return ListSuccessResponse(data=entries, meta=meta)


# ------------------------------ fulfillments ------------------------------ #


@router.get("/fulfillments", response_model=ListSuccessResponse[FulfillmentResponse])
async def merchant_fulfillments(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[FulfillmentListQuery, Query()],
    service: FulfillmentLogServiceDep,
):
    fulfillments, meta = await service.list_fulfillments(merchant, query, uow)
    return ListSuccessResponse(data=fulfillments, meta=meta)


@router.get("/fulfillments/{fulfillment_id}", response_model=SuccessResponse[FulfillmentResponse])
async def merchant_fulfillment(
    merchant: ViewedMerchant,
    fulfillment_id: UUID,
    uow: UnitOfWorkRepo,
    service: FulfillmentLogServiceDep,
):
    return SuccessResponse(data=await service.get_fulfillment(merchant, fulfillment_id, uow))


# ------------------------------ reconciliation ------------------------------ #


@router.get("/reconciliation/current", response_model=SuccessResponse[ReconciliationView])
async def merchant_reconciliation(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: ReconciliationServiceDep
):
    return SuccessResponse(data=await service.current(merchant, uow))


@router.get("/reconciliation/summary", response_model=SuccessResponse[ReconciliationSummary])
async def merchant_reconciliation_summary(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: ReconciliationServiceDep
):
    return SuccessResponse(data=await service.summary(merchant, uow))


@router.get(
    "/reconciliation/sessions",
    response_model=ListSuccessResponse[ReconciliationSessionResponse],
)
async def merchant_reconciliation_sessions(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    params: Annotated[PageParams, Query()],
    service: ReconciliationServiceDep,
):
    sessions, meta = await service.list_sessions(merchant, params, uow)
    return ListSuccessResponse(data=sessions, meta=meta)


@router.get(
    "/reconciliation/sessions/{session_id}",
    response_model=SuccessResponse[ReconciliationView],
)
async def merchant_reconciliation_session(
    merchant: ViewedMerchant,
    session_id: UUID,
    uow: UnitOfWorkRepo,
    service: ReconciliationServiceDep,
):
    return SuccessResponse(data=await service.get_session(merchant, session_id, uow))


# ------------------------------ disputes ------------------------------ #


@router.get("/disputes", response_model=ListSuccessResponse[DisputeSummary])
async def merchant_disputes(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[DisputeListQuery, Query()],
    service: DisputeServiceDep,
):
    disputes, meta = await service.list_disputes(merchant, query, uow)
    return ListSuccessResponse(data=disputes, meta=meta)


@router.get("/disputes/stats", response_model=SuccessResponse[DisputeStats])
async def merchant_dispute_stats(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: DisputeServiceDep
):
    return SuccessResponse(data=await service.stats(merchant, uow))


@router.get("/disputes/{dispute_id}", response_model=SuccessResponse[DisputeDetail])
async def merchant_dispute(
    merchant: ViewedMerchant, dispute_id: UUID, uow: UnitOfWorkRepo, service: DisputeServiceDep
):
    """The dispute with its evidence document, as the merchant's review screen shows it"""
    return SuccessResponse(data=await service.get_dispute(merchant, dispute_id, uow))


@router.get(
    "/disputes/{dispute_id}/evidence-pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def merchant_dispute_pdf(
    merchant: ViewedMerchant,
    dispute_id: UUID,
    uow: UnitOfWorkRepo,
    service: DisputeServiceDep,
    storage: MinioDep,
):
    content, filename = await service.evidence_pdf(merchant, dispute_id, uow, storage)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------ trust ------------------------------ #
# 404 for a merchant who never opened TrustLayer: viewing never creates their profile


@router.get("/trust/profile", response_model=SuccessResponse[TrustProfileResponse])
async def merchant_trust_profile(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: TrustServiceDep
):
    return SuccessResponse(data=await service.get_profile(merchant, uow, create=False))


@router.get("/trust/signals", response_model=SuccessResponse[TrustSignalsBreakdown])
async def merchant_trust_signals(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: TrustServiceDep
):
    return SuccessResponse(data=await service.signals(merchant, uow, create=False))


@router.get("/trust/actions", response_model=SuccessResponse[TrustActions])
async def merchant_trust_actions(
    merchant: ViewedMerchant, uow: UnitOfWorkRepo, service: TrustServiceDep
):
    return SuccessResponse(data=await service.actions(merchant, uow, create=False))


@router.get("/trust/history", response_model=SuccessResponse[TrustHistory])
async def merchant_trust_history(
    merchant: ViewedMerchant,
    uow: UnitOfWorkRepo,
    query: Annotated[TrustHistoryQuery, Query()],
    service: TrustServiceDep,
):
    return SuccessResponse(data=await service.history(merchant, query.days, uow))
