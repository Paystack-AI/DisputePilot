from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from app.api.schemas.fulfillments import (
    FulfillmentCreate,
    FulfillmentListQuery,
    FulfillmentResponse,
    FulfillmentUpdate,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.api.services import trust_triggers
from app.deps import (
    CurrentMerchant,
    FulfillmentLogServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/fulfillments",
    status_code=200,
    response_model=ListSuccessResponse[FulfillmentResponse],
    description="List fulfillments with their proof photos. Filters: order_id, transaction_id",
    dependencies=[read_limiter],
)
async def list_fulfillments(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[FulfillmentListQuery, Query()],
    fulfillment_log_service: FulfillmentLogServiceDep,
):
    fulfillments, meta = await fulfillment_log_service.list_fulfillments(curr_merchant, query, uow)
    return ListSuccessResponse(data=fulfillments, meta=meta)


@router.post(
    "/fulfillments",
    status_code=201,
    response_model=SuccessResponse[FulfillmentResponse],
    description=(
        "Log a fulfillment for an order. Photos are uploaded first (POST /uploads) and "
        "attached by id. A paid order becomes fulfilled. transaction_id defaults to the "
        "order's linked payment. Send an Idempotency-Key (e.g. a uuid per save) and reuse "
        "it on retries: a repeat returns the first fulfillment instead of a duplicate"
    ),
    dependencies=[write_limiter],
)
async def create_fulfillment(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: FulfillmentCreate,
    fulfillment_log_service: FulfillmentLogServiceDep,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
):
    fulfillment: FulfillmentResponse = await fulfillment_log_service.create_fulfillment(
        curr_merchant, payload, uow, idempotency_key
    )
    # the change is committed: queue the merchant's trust recomputation
    await trust_triggers.request_trust_update(curr_merchant.id, trust_triggers.FULFILLMENT_LOGGED)
    return SuccessResponse(data=fulfillment)


@router.get(
    "/fulfillments/{fulfillment_id}",
    status_code=200,
    response_model=SuccessResponse[FulfillmentResponse],
    description="Single fulfillment with all its proof photos",
    dependencies=[read_limiter],
)
async def get_fulfillment(
    fulfillment_id: UUID,
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    fulfillment_log_service: FulfillmentLogServiceDep,
):
    fulfillment: FulfillmentResponse = await fulfillment_log_service.get_fulfillment(
        curr_merchant, fulfillment_id, uow
    )
    return SuccessResponse(data=fulfillment)


@router.patch(
    "/fulfillments/{fulfillment_id}",
    status_code=200,
    response_model=SuccessResponse[FulfillmentResponse],
    description=(
        "Update fulfillment details. file_ids replaces the attached photos; removed photos "
        "are deleted after a day"
    ),
    dependencies=[write_limiter],
)
async def update_fulfillment(
    fulfillment_id: UUID,
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: FulfillmentUpdate,
    fulfillment_log_service: FulfillmentLogServiceDep,
):
    fulfillment: FulfillmentResponse = await fulfillment_log_service.update_fulfillment(
        curr_merchant, fulfillment_id, payload, uow
    )
    # the change is committed: queue the merchant's trust recomputation
    await trust_triggers.request_trust_update(curr_merchant.id, trust_triggers.FULFILLMENT_LOGGED)
    return SuccessResponse(data=fulfillment)
