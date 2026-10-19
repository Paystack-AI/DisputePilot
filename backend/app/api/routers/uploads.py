from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.routing import APIRoute

from app.api.schemas.files import FileResponse, UploadResult
from app.api.schemas.response import SuccessResponse
from app.api.services.uploads import MAX_FILE_MB
from app.core.config import get_settings
from app.core.exceptions import PayloadTooLargeError
from app.deps import (
    CurrentMerchant,
    MinioDep,
    UnitOfWorkRepo,
    UploadServiceDep,
    read_limiter,
    write_limiter,
)

SETTINGS = get_settings()

# every file at the limit plus room for the multipart boundaries and headers
MAX_REQUEST_BYTES: int = SETTINGS.UPLOAD_MAX_FILES * SETTINGS.UPLOAD_MAX_FILE_BYTES + 1024 * 1024


class UploadSizeLimitRoute(APIRoute):
    """Rejects an oversized request from its Content-Length before the body is received.
    FastAPI parses form bodies before running dependencies, so a dependency would only see
    it after the whole upload arrived. Each file's own size is checked in the service"""

    def get_route_handler(self) -> Callable:
        handler: Callable = super().get_route_handler()

        async def limited_handler(request: Request) -> Response:
            content_length: str | None = request.headers.get("content-length")
            if content_length and content_length.isdigit():
                if int(content_length) > MAX_REQUEST_BYTES:
                    raise PayloadTooLargeError(MAX_FILE_MB)
            return await handler(request)

        return limited_handler


router = APIRouter(route_class=UploadSizeLimitRoute)


@router.post(
    "/uploads",
    status_code=201,
    response_model=SuccessResponse[UploadResult],
    description=(
        f"Upload 1 to {SETTINGS.UPLOAD_MAX_FILES} images (multipart field 'files', "
        f"{MAX_FILE_MB} MB each): JPEG, PNG, WebP or HEIC (stored as JPEG). The type is "
        "checked from the content. Images are stored upright without metadata (location "
        "included). Returns their ids, in the order sent, to attach to a fulfillment; "
        "unattached uploads are deleted after a day"
    ),
    dependencies=[write_limiter],
)
async def upload_images(
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    storage: MinioDep,
    upload_service: UploadServiceDep,
    files: list[UploadFile] = File(...),  # noqa: B008
):
    uploaded: list[FileResponse] = await upload_service.upload_images(
        curr_merchant, files, uow, storage
    )
    return SuccessResponse(data=UploadResult(files=uploaded))


@router.get(
    "/uploads/{file_id}",
    status_code=200,
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}},
    description="The image itself, for the merchant who uploaded it",
    dependencies=[read_limiter],
)
async def get_image(
    file_id: UUID,
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    storage: MinioDep,
    upload_service: UploadServiceDep,
):
    stored_file, data = await upload_service.get_image(curr_merchant, file_id, uow, storage)
    return Response(
        content=data,
        media_type=stored_file.content_type,
        headers={
            # the bytes behind an id never change, but the response is per merchant
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/uploads/{file_id}",
    status_code=204,
    response_class=Response,
    description=(
        "Delete an upload that is not attached to anything. An attached photo returns 409 "
        "FILE_ALREADY_ATTACHED: remove it from its fulfillment (PATCH file_ids) first"
    ),
    dependencies=[write_limiter],
)
async def delete_image(
    file_id: UUID,
    uow: UnitOfWorkRepo,
    curr_merchant: CurrentMerchant,
    storage: MinioDep,
    upload_service: UploadServiceDep,
):
    await upload_service.delete_image(curr_merchant, file_id, uow, storage)
    return Response(status_code=204)
