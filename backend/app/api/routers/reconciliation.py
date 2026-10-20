from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.schemas.pagination import PageParams
from app.api.schemas.reconciliation import (
    MatchDecision,
    MatchDecisionResponse,
    ReconciliationSessionResponse,
    ReconciliationStart,
    ReconciliationSummary,
    ReconciliationView,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.deps import (
    CurrentMerchant,
    ReconciliationServiceDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter(prefix="/reconciliation")


@router.post(
    "/start",
    status_code=201,
    response_model=SuccessResponse[ReconciliationView],
    description=(
        "Open a session for a range of days (merchant's timezone, both inclusive, at most 31; "
        "omitted: the default reconciliation range ending today) and run the matching tiers "
        "on it. With a session already open it is continued instead (200; the range sent is "
        "ignored). Starting the first one finishes onboarding"
    ),
    dependencies=[write_limiter],
)
async def start_reconciliation(
    response: Response,
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: ReconciliationStart,
    reconciliation_service: ReconciliationServiceDep,
):
    view, created = await reconciliation_service.start(curr_merchant, payload, uow)
    if not created:
        response.status_code = 200
    return SuccessResponse(data=view)


@router.get(
    "/current",
    status_code=200,
    response_model=SuccessResponse[ReconciliationView],
    description=(
        "The open session (else the latest) with its payments by category: matched, "
        "suggestions, unmatched_payments, unmatched_orders, flagged, flagged_orders. Up to 200 "
        "per list, newest first; totals has the full counts. 404 before the first session"
    ),
    dependencies=[read_limiter],
)
async def current_reconciliation(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reconciliation_service: ReconciliationServiceDep,
):
    view: ReconciliationView = await reconciliation_service.current(curr_merchant, uow)
    return SuccessResponse(data=view)


@router.get(
    "/sessions",
    status_code=200,
    response_model=ListSuccessResponse[ReconciliationSessionResponse],
    description="Past and open sessions, newest first",
    dependencies=[read_limiter],
)
async def list_reconciliation_sessions(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    params: Annotated[PageParams, Query()],
    reconciliation_service: ReconciliationServiceDep,
):
    sessions, meta = await reconciliation_service.list_sessions(curr_merchant, params, uow)
    return ListSuccessResponse(data=sessions, meta=meta)


@router.get(
    "/sessions/{session_id}",
    status_code=200,
    response_model=SuccessResponse[ReconciliationView],
    description="One session with its payments by category, like /reconciliation/current",
    dependencies=[read_limiter],
)
async def get_reconciliation_session(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    session_id: UUID,
    reconciliation_service: ReconciliationServiceDep,
):
    view: ReconciliationView = await reconciliation_service.get_session(
        curr_merchant, session_id, uow
    )
    return SuccessResponse(data=view)


@router.post(
    "/accept-match",
    status_code=200,
    response_model=SuccessResponse[MatchDecisionResponse],
    description=(
        "Confirm a suggestion: the payment is linked (manually_matched) and the order becomes "
        "paid. Safe to retry: accepting a pair already linked returns it unchanged. 404 "
        "without a pending suggestion; 409 MATCH_CONFLICT when either side was settled since"
    ),
    dependencies=[write_limiter],
)
async def accept_match(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: MatchDecision,
    reconciliation_service: ReconciliationServiceDep,
):
    decided: MatchDecisionResponse = await reconciliation_service.accept_match(
        curr_merchant, payload, uow
    )
    return SuccessResponse(data=decided)


@router.post(
    "/reject-match",
    status_code=200,
    response_model=SuccessResponse[MatchDecisionResponse],
    description=(
        "Reject a suggestion, or undo an automatic match (the order goes back to pending). "
        "The pair is never matched or suggested again. 404 when the pair is neither; 409 "
        "MATCH_CONFLICT (order_fulfilled) for an order already fulfilled"
    ),
    dependencies=[write_limiter],
)
async def reject_match(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    payload: MatchDecision,
    reconciliation_service: ReconciliationServiceDep,
):
    decided: MatchDecisionResponse = await reconciliation_service.reject_match(
        curr_merchant, payload, uow
    )
    return SuccessResponse(data=decided)


@router.post(
    "/complete",
    status_code=200,
    response_model=SuccessResponse[ReconciliationSessionResponse],
    description=(
        "Close the open session with its counts and email the summary (when email "
        "notifications are on). 404 when no session is open"
    ),
    dependencies=[write_limiter],
)
async def complete_reconciliation(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reconciliation_service: ReconciliationServiceDep,
):
    session: ReconciliationSessionResponse = await reconciliation_service.complete(
        curr_merchant, uow
    )
    return SuccessResponse(data=session)


@router.get(
    "/summary",
    status_code=200,
    response_model=SuccessResponse[ReconciliationSummary],
    description=(
        "Quick stats: payments synced and matched today, payments needing review (last 30 "
        "days) and when a session was last completed"
    ),
    dependencies=[read_limiter],
)
async def reconciliation_summary(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    reconciliation_service: ReconciliationServiceDep,
):
    summary: ReconciliationSummary = await reconciliation_service.summary(curr_merchant, uow)
    return SuccessResponse(data=summary)
