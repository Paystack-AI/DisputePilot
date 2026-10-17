from typing import Annotated

from fastapi import APIRouter, Query

from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.api.schemas.transactions import (
    TransactionDetail,
    TransactionFlag,
    TransactionListQuery,
    TransactionMatch,
    TransactionResponse,
    TransactionSyncResponse,
)
from app.deps import (
    CurrentMerchant,
    TransactionServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter()


@router.get(
    "/transactions",
    status_code=200,
    response_model=ListSuccessResponse[TransactionResponse],
    description=(
        "List synced Paystack transactions, paid or not. Filters: status and "
        "reconciliation_status (comma lists; status=success for paid only), customer_id, "
        "date_from / date_to (YYYY-MM-DD in the merchant's timezone, on when the attempt "
        "started). Sort: created_at (default, newest first), paid_at or amount, - for "
        "descending"
    ),
    dependencies=[read_limiter],
)
async def list_transactions(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[TransactionListQuery, Query()],
    transaction_service: TransactionServiceDep,
):
    transactions, meta = await transaction_service.list_transactions(curr_merchant, query, uow)
    return ListSuccessResponse(data=transactions, meta=meta)


@router.post(
    "/transactions/sync",
    status_code=202,
    response_model=SuccessResponse[TransactionSyncResponse],
    description=(
        "Queue a sync from Paystack, from the last finished sync to now. 422 "
        "PAYSTACK_NOT_CONNECTED without a key; 409 SYNC_IN_PROGRESS during the initial sync"
    ),
    dependencies=[write_limiter],
)
async def sync_transactions(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    transaction_service: TransactionServiceDep,
):
    queued: TransactionSyncResponse = await transaction_service.sync_transactions(
        curr_merchant, uow
    )
    return SuccessResponse(data=queued)


@router.get(
    "/transactions/{reference}",
    status_code=200,
    response_model=SuccessResponse[TransactionDetail],
    description=(
        "Single transaction by Paystack reference, with its order, fulfillments and dispute"
    ),
    dependencies=[read_limiter],
)
async def get_transaction(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reference: str,
    transaction_service: TransactionServiceDep,
):
    transaction: TransactionDetail = await transaction_service.get_transaction(
        curr_merchant, reference, uow
    )
    return SuccessResponse(data=transaction)


@router.put(
    "/transactions/{reference}/match",
    status_code=200,
    response_model=SuccessResponse[TransactionResponse],
    description=(
        "Match the transaction to an order by hand (manually_matched; a pending order becomes "
        "paid). 409 MATCH_CONFLICT with details.reason when the match isn't possible"
    ),
    dependencies=[write_limiter],
)
async def match_transaction(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reference: str,
    payload: TransactionMatch,
    transaction_service: TransactionServiceDep,
):
    transaction: TransactionResponse = await transaction_service.match_transaction(
        curr_merchant, reference, payload, uow
    )
    return SuccessResponse(data=transaction)


@router.put(
    "/transactions/{reference}/flag",
    status_code=200,
    response_model=SuccessResponse[TransactionResponse],
    description="Flag the transaction for review with a reason",
    dependencies=[write_limiter],
)
async def flag_transaction(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reference: str,
    payload: TransactionFlag,
    transaction_service: TransactionServiceDep,
):
    transaction: TransactionResponse = await transaction_service.flag_transaction(
        curr_merchant, reference, payload, uow
    )
    return SuccessResponse(data=transaction)


@router.put(
    "/transactions/{reference}/unflag",
    status_code=200,
    response_model=SuccessResponse[TransactionResponse],
    description=("Remove the flag: manually_matched when linked to an order, unmatched otherwise"),
    dependencies=[write_limiter],
)
async def unflag_transaction(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reference: str,
    transaction_service: TransactionServiceDep,
):
    transaction: TransactionResponse = await transaction_service.unflag_transaction(
        curr_merchant, reference, uow
    )
    return SuccessResponse(data=transaction)
