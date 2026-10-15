from fastapi import APIRouter

from app.api.schemas.merchants import PaystackConnection
from app.api.schemas.paystack import PaystackConnect
from app.api.schemas.response import SuccessResponse
from app.deps import (
    CurrentMerchant,
    PaystackServiceDep,
    SecurityDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.post(
    "/auth/paystack/connect",
    status_code=200,
    response_model=SuccessResponse[PaystackConnection],
    description=(
        "Connect the merchant's Paystack account with their secret key, or rotate it. "
        "The key is encrypted and never returned, and the transaction sync starts afterwards"
    ),
    dependencies=[write_limiter],
)
async def connect_paystack(
    uow: UnitOfWorkRepo,
    security: SecurityDep,
    curr_merchant: CurrentMerchant,
    connect_payload: PaystackConnect,
    paystack_service: PaystackServiceDep,
):
    connection: PaystackConnection = await paystack_service.connect(
        curr_merchant, connect_payload, security, uow
    )
    return SuccessResponse(data=connection)


@router.get(
    "/auth/paystack/status",
    status_code=200,
    response_model=SuccessResponse[PaystackConnection],
    description="Paystack connection status of the current merchant",
    dependencies=[read_limiter],
)
async def get_paystack_status(
    curr_merchant: CurrentMerchant,
    paystack_service: PaystackServiceDep,
):
    connection: PaystackConnection = await paystack_service.get_connection(curr_merchant)
    return SuccessResponse(data=connection)
