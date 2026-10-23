from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from app.api.repo.ai_memory import AiMemoryRepository
from app.api.schemas.ai_memory import MemoryCorrection, MemoryMutationResponse
from app.api.schemas.response import SuccessResponse
from app.core.exceptions import NotFoundError
from app.deps import CurrentMerchant, UnitOfWorkRepo, write_limiter

router = APIRouter()


@router.post(
    "/ai/memory/{memory_id}/correction",
    status_code=200,
    response_model=SuccessResponse[MemoryMutationResponse],
    dependencies=[write_limiter],
    description="Replace one of the merchant's AI memory records with an auditable correction",
)
async def correct_memory(
    memory_id: Annotated[UUID, Path()],
    payload: MemoryCorrection,
    curr_merchant: CurrentMerchant,
    uow: UnitOfWorkRepo,
):
    memory = await uow.repo(AiMemoryRepository).correct_memory(
        curr_merchant.id, curr_merchant.id, memory_id, payload.content, payload.reason
    )
    if memory is None:
        raise NotFoundError("AI memory")
    await uow.commit()
    return SuccessResponse(data=MemoryMutationResponse(id=memory.id))


@router.delete(
    "/ai/memory/{memory_id}",
    status_code=200,
    response_model=SuccessResponse[MemoryMutationResponse],
    dependencies=[write_limiter],
    description="Soft-delete one of the merchant's AI memory records",
)
async def delete_memory(
    memory_id: Annotated[UUID, Path()],
    curr_merchant: CurrentMerchant,
    uow: UnitOfWorkRepo,
):
    deleted = await uow.repo(AiMemoryRepository).delete_memory(
        curr_merchant.id, curr_merchant.id, memory_id, "merchant_requested"
    )
    if not deleted:
        raise NotFoundError("AI memory")
    await uow.commit()
    return SuccessResponse(data=MemoryMutationResponse(id=memory_id, deleted=True))
