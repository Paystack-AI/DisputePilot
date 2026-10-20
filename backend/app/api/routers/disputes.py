from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.schemas.disputes import (
    DisputeAccept,
    DisputeDetail,
    DisputeListQuery,
    DisputeStats,
    DisputeSummary,
    DisputeSyncQueued,
    EvidenceQueued,
    EvidenceSubmit,
    EvidenceUpdate,
    SubmissionQueued,
)
from app.api.schemas.response import ListSuccessResponse, SuccessResponse
from app.deps import (
    CurrentMerchant,
    DisputeServiceDep,
    MinioDep,
    UnitOfWorkRepo,
    read_limiter,
    write_limiter,
)

router = APIRouter(prefix="/disputes")


@router.get(
    "",
    status_code=200,
    response_model=ListSuccessResponse[DisputeSummary],
    description=(
        "List disputes. Filters (comma lists): status, category, urgency (critical under 4h, "
        "warning 4-8h, safe over 8h; only disputes still awaiting a response). Sort: "
        "created_at (default, newest first) or due_at, - for descending. meta.server_time "
        "is for countdowns"
    ),
    dependencies=[read_limiter],
)
async def list_disputes(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    query: Annotated[DisputeListQuery, Query()],
    dispute_service: DisputeServiceDep,
):
    disputes, meta = await dispute_service.list_disputes(curr_merchant, query, uow)
    return ListSuccessResponse(data=disputes, meta=meta)


@router.get(
    "/stats",
    status_code=200,
    response_model=SuccessResponse[DisputeStats],
    description="Totals by outcome, win rate after responding, and average response time",
    dependencies=[read_limiter],
)
async def dispute_stats(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_service: DisputeServiceDep,
):
    return SuccessResponse(data=await dispute_service.stats(curr_merchant, uow))


@router.post(
    "/sync",
    status_code=202,
    response_model=SuccessResponse[DisputeSyncQueued],
    description=(
        "Queue a check of Paystack for new and changed disputes; they arrive as "
        "dispute.created / dispute.updated events. 422 PAYSTACK_NOT_CONNECTED without a key"
    ),
    dependencies=[write_limiter],
)
async def sync_disputes(curr_merchant: CurrentMerchant, dispute_service: DisputeServiceDep):
    return SuccessResponse(data=await dispute_service.sync(curr_merchant))


@router.get(
    "/{dispute_id}",
    status_code=200,
    response_model=SuccessResponse[DisputeDetail],
    description=(
        "One dispute with everything the review screen needs: the evidence document "
        "(facts from the records, plus the editable narrative, documents and conclusion), "
        "readiness, quality, allowed_actions and server_time"
    ),
    dependencies=[read_limiter],
)
async def get_dispute(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    dispute_service: DisputeServiceDep,
):
    return SuccessResponse(data=await dispute_service.get_dispute(curr_merchant, dispute_id, uow))


@router.post(
    "/{dispute_id}/generate-evidence",
    status_code=202,
    response_model=SuccessResponse[EvidenceQueued],
    description=(
        "Start the ai: classify, write the narrative, score it. Progress arrives as "
        "evidence.progress events and the finished draft as evidence.ready (the full "
        "evidence document). Calling it while a run is in progress returns that run. 409 "
        "DISPUTE_ACTION_NOT_ALLOWED once the dispute can no longer be answered"
    ),
    dependencies=[write_limiter],
)
async def generate_evidence(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    dispute_service: DisputeServiceDep,
):
    queued: EvidenceQueued = await dispute_service.generate_evidence(curr_merchant, dispute_id, uow)
    return SuccessResponse(data=queued)


@router.put(
    "/{dispute_id}/evidence",
    status_code=200,
    response_model=SuccessResponse[DisputeDetail],
    description=(
        "Edit the narrative, the conclusion and the attached documents (the complete list; "
        "upload images through /uploads first), with a reason for the change. Send the "
        "evidence version you edited: 409 EVIDENCE_VERSION_CONFLICT when it moved on"
    ),
    dependencies=[write_limiter],
)
async def update_evidence(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    payload: EvidenceUpdate,
    dispute_service: DisputeServiceDep,
):
    detail: DisputeDetail = await dispute_service.update_evidence(
        curr_merchant, dispute_id, payload, uow
    )
    return SuccessResponse(data=detail)


@router.post(
    "/{dispute_id}/submit",
    status_code=202,
    response_model=SuccessResponse[SubmissionQueued],
    description=(
        "Approve the evidence version sent and respond to Paystack (decline): the pdf is "
        "generated and submitted through the chargeback or fraud flow in the background. "
        "dispute.updated reports submitted or failed, and the pdf is emailed. 409 "
        "EVIDENCE_VERSION_CONFLICT; 422 FRAUD_EVIDENCE_INCOMPLETE for a fraud claim missing "
        "the customer details Paystack requires"
    ),
    dependencies=[write_limiter],
)
async def submit_dispute(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    payload: EvidenceSubmit,
    dispute_service: DisputeServiceDep,
):
    queued: SubmissionQueued = await dispute_service.submit(curr_merchant, dispute_id, payload, uow)
    return SuccessResponse(data=queued)


@router.post(
    "/{dispute_id}/accept",
    status_code=202,
    response_model=SuccessResponse[SubmissionQueued],
    description=(
        "Accept the dispute when the claim is right: Paystack refunds the customer. Runs in "
        "the background; dispute.updated reports accepted or failed"
    ),
    dependencies=[write_limiter],
)
async def accept_dispute(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    payload: DisputeAccept,
    dispute_service: DisputeServiceDep,
):
    queued: SubmissionQueued = await dispute_service.accept(curr_merchant, dispute_id, payload, uow)
    return SuccessResponse(data=queued)


@router.get(
    "/{dispute_id}/evidence-pdf",
    status_code=200,
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    description="Download the evidence pdf that was submitted. 404 before submission",
    dependencies=[read_limiter],
)
async def evidence_pdf(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    dispute_id: UUID,
    dispute_service: DisputeServiceDep,
    storage: MinioDep,
):
    content, filename = await dispute_service.evidence_pdf(curr_merchant, dispute_id, uow, storage)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
