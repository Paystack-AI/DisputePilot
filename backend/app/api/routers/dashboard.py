from typing import Annotated

from fastapi import APIRouter, Query

from app.api.schemas.dashboard import (
    ChartQuery,
    Dashboard,
    DashboardQuery,
    DisputeTimeline,
    ReconciliationHealth,
)
from app.api.schemas.response import SuccessResponse
from app.deps import CurrentMerchant, DashboardServiceDep, UnitOfWorkRepo, read_limiter

router = APIRouter(prefix="/dashboard")


@router.get(
    "",
    status_code=200,
    response_model=SuccessResponse[Dashboard],
    description=(
        "Everything for the first paint: metrics for the period (date_from / date_to, days "
        "in the merchant's timezone; default the last 7) against the period of the same "
        "length before it, the critical dispute, reconciliation, trust, fulfillment prompts, "
        "recent transactions and disputes, and the activity feed. Each block is null on its "
        "own if it fails. Counts only: no revenue, payout or settlement figures"
    ),
    dependencies=[read_limiter],
)
async def get_dashboard(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[DashboardQuery, Query()],
    dashboard_service: DashboardServiceDep,
):
    return SuccessResponse(data=await dashboard_service.dashboard(curr_merchant, query, uow))


@router.get(
    "/dispute-timeline",
    status_code=200,
    response_model=SuccessResponse[DisputeTimeline],
    description="Per day over 30 or 90 days: disputes opened, won, lost and auto-accepted",
    dependencies=[read_limiter],
)
async def dispute_timeline(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[ChartQuery, Query()],
    dashboard_service: DashboardServiceDep,
):
    timeline: DisputeTimeline = await dashboard_service.dispute_timeline(
        curr_merchant, query.days, uow
    )
    return SuccessResponse(data=timeline)


@router.get(
    "/reconciliation-health",
    status_code=200,
    response_model=SuccessResponse[ReconciliationHealth],
    description=(
        "Over 30 or 90 days: sessions started and completed, the completion rate, average "
        "mismatches per completed session, and the daily match rate"
    ),
    dependencies=[read_limiter],
)
async def reconciliation_health(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[ChartQuery, Query()],
    dashboard_service: DashboardServiceDep,
):
    health: ReconciliationHealth = await dashboard_service.reconciliation_health(
        curr_merchant, query.days, uow
    )
    return SuccessResponse(data=health)
