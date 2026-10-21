from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.schemas.customers import (
    CustomerCreate,
    CustomerListQuery,
    CustomerResponse,
    CustomerSummary,
    CustomerUpdate,
    LedgerEntry,
)
from app.api.schemas.disputes import DisputeSummary
from app.api.schemas.orders import OrderResponse
from app.api.schemas.pagination import PageParams
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.api.schemas.transactions import TransactionSummary
from app.deps import (
    CurrentMerchant,
    CustomerLedgerServiceDep,
    DisputeServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/customers",
    status_code=200,
    response_model=ListSuccessResponse[CustomerSummary],
    description=(
        "List customers (one per payer email) with ledger counts. Search matches name or "
        "email. No money totals"
    ),
    dependencies=[read_limiter],
)
async def list_customers(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[CustomerListQuery, Query()],
    customer_ledger_service: CustomerLedgerServiceDep,
):
    customers, meta = await customer_ledger_service.list_customers(curr_merchant, query, uow)
    return ListSuccessResponse(data=customers, meta=meta)


@router.post(
    "/customers",
    status_code=201,
    response_model=SuccessResponse[CustomerResponse],
    description=(
        "Add a customer manually, e.g. a cash customer. Name or email is required; an email "
        "the merchant already has returns 409 CUSTOMER_EXISTS with details.customer_id"
    ),
    dependencies=[write_limiter],
)
async def create_customer(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: CustomerCreate,
    customer_ledger_service: CustomerLedgerServiceDep,
):
    customer: CustomerResponse = await customer_ledger_service.create_customer(
        curr_merchant, payload, uow
    )
    return SuccessResponse(data=customer)


@router.get(
    "/customers/{customer_id}",
    status_code=200,
    response_model=SuccessResponse[CustomerResponse],
    description="Single customer with ledger stats (counts only)",
    dependencies=[read_limiter],
)
async def get_customer(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    customer_ledger_service: CustomerLedgerServiceDep,
):
    customer: CustomerResponse = await customer_ledger_service.get_customer(
        curr_merchant, customer_id, uow
    )
    return SuccessResponse(data=customer)


@router.patch(
    "/customers/{customer_id}",
    status_code=200,
    response_model=SuccessResponse[CustomerResponse],
    description=(
        "Update name, phone, email or the shared flag. The email can only change while the "
        "customer has no synced payments (409 CUSTOMER_EMAIL_LOCKED)"
    ),
    dependencies=[write_limiter],
)
async def update_customer(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    payload: CustomerUpdate,
    customer_ledger_service: CustomerLedgerServiceDep,
):
    customer: CustomerResponse = await customer_ledger_service.update_customer(
        curr_merchant, customer_id, payload, uow
    )
    return SuccessResponse(data=customer)


@router.get(
    "/customers/{customer_id}/transactions",
    status_code=200,
    response_model=ListSuccessResponse[TransactionSummary],
    description="Synced payments for this customer, newest first",
    dependencies=[read_limiter],
)
async def list_customer_transactions(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    params: Annotated[PageParams, Query()],
    customer_ledger_service: CustomerLedgerServiceDep,
):
    transactions, meta = await customer_ledger_service.list_customer_transactions(
        curr_merchant, customer_id, params, uow
    )
    return ListSuccessResponse(data=transactions, meta=meta)


@router.get(
    "/customers/{customer_id}/orders",
    status_code=200,
    response_model=ListSuccessResponse[OrderResponse],
    description="Orders for this customer, newest first",
    dependencies=[read_limiter],
)
async def list_customer_orders(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    params: Annotated[PageParams, Query()],
    customer_ledger_service: CustomerLedgerServiceDep,
):
    orders, meta = await customer_ledger_service.list_customer_orders(
        curr_merchant, customer_id, params, uow
    )
    return ListSuccessResponse(data=orders, meta=meta)


@router.get(
    "/customers/{customer_id}/disputes",
    status_code=200,
    response_model=ListSuccessResponse[DisputeSummary],
    description="Disputes on this customer's payments, newest first",
    dependencies=[read_limiter],
)
async def list_customer_disputes(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    params: Annotated[PageParams, Query()],
    customer_ledger_service: CustomerLedgerServiceDep,
    dispute_service: DisputeServiceDep,
):
    disputes, meta = await customer_ledger_service.list_customer_disputes(
        curr_merchant, customer_id, params, uow, dispute_service
    )
    return ListSuccessResponse(data=disputes, meta=meta)


@router.get(
    "/customers/{customer_id}/ledger",
    status_code=200,
    response_model=ListSuccessResponse[LedgerEntry],
    description=(
        "The customer's full ledger: payments, orders, disputes and fulfillments as one "
        "timeline, newest first"
    ),
    dependencies=[read_limiter],
)
async def customer_ledger(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    customer_id: UUID,
    params: Annotated[PageParams, Query()],
    customer_ledger_service: CustomerLedgerServiceDep,
):
    entries, meta = await customer_ledger_service.customer_ledger(
        curr_merchant, customer_id, params, uow
    )
    return ListSuccessResponse(data=entries, meta=meta)
