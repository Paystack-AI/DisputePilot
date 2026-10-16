from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.schemas.orders import (
    OrderCreate,
    OrderDetail,
    OrderListQuery,
    OrderResponse,
    OrderUpdate,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.deps import (
    CurrentMerchant,
    OrderManagementServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/orders",
    status_code=200,
    response_model=ListSuccessResponse[OrderResponse],
    description=(
        "List orders. Filters: status (comma list), customer_id, date_from / date_to "
        "(YYYY-MM-DD in the merchant's timezone), search (number, description, customer)"
    ),
    dependencies=[read_limiter],
)
async def list_orders(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[OrderListQuery, Query()],
    order_management_service: OrderManagementServiceDep,
):
    orders, meta = await order_management_service.list_orders(curr_merchant, query, uow)
    return ListSuccessResponse(data=orders, meta=meta)


@router.post(
    "/orders",
    status_code=201,
    response_model=SuccessResponse[OrderResponse],
    description=(
        "Create an order. order_number is optional (409 ORDER_NUMBER_EXISTS if taken); "
        "customer_email links to or creates the customer; currency defaults to the "
        "merchant's default currency"
    ),
    dependencies=[write_limiter],
)
async def create_order(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: OrderCreate,
    order_management_service: OrderManagementServiceDep,
):
    order: OrderResponse = await order_management_service.create_order(curr_merchant, payload, uow)
    return SuccessResponse(data=order)


@router.get(
    "/orders/{order_id}",
    status_code=200,
    response_model=SuccessResponse[OrderDetail],
    description="Single order with its customer, linked transactions and fulfillments",
    dependencies=[read_limiter],
)
async def get_order(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    order_id: UUID,
    order_management_service: OrderManagementServiceDep,
):
    order: OrderDetail = await order_management_service.get_order(curr_merchant, order_id, uow)
    return SuccessResponse(data=order)


@router.patch(
    "/orders/{order_id}",
    status_code=200,
    response_model=SuccessResponse[OrderResponse],
    description=(
        "Update an order. Once linked to a payment, order_number, amount, currency and "
        "customer are locked (409 ORDER_LINKED). Status: pending to cancelled, paid to "
        "fulfilled; paid is set by reconciliation (409 ORDER_STATUS_TRANSITION)"
    ),
    dependencies=[write_limiter],
)
async def update_order(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    order_id: UUID,
    payload: OrderUpdate,
    order_management_service: OrderManagementServiceDep,
):
    order: OrderResponse = await order_management_service.update_order(
        curr_merchant, order_id, payload, uow
    )
    return SuccessResponse(data=order)


@router.delete(
    "/orders/{order_id}",
    status_code=200,
    response_model=SuccessResponse[OrderResponse],
    description=(
        "Soft delete: sets the status to cancelled. Linked orders are unlinked in "
        "reconciliation first (409 ORDER_LINKED)"
    ),
    dependencies=[write_limiter],
)
async def cancel_order(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    order_id: UUID,
    order_management_service: OrderManagementServiceDep,
):
    order: OrderResponse = await order_management_service.cancel_order(curr_merchant, order_id, uow)
    return SuccessResponse(data=order)
