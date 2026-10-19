import uuid
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool

from app.api.clients.minio import MinioStorage
from app.api.models.files import StoredFile
from app.api.models.merchants import Merchant
from app.api.repo.files import FileRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.files import FileInDB, FileResponse
from app.api.services.files import FileService
from app.api.services.images import NotAnImageError, ProcessedImage, process_image
from app.core.config import get_settings
from app.core.exceptions import (
    FileAlreadyAttachedError,
    NotFoundError,
    PayloadTooLargeError,
    ServerError,
    UnsupportedFileTypeError,
)

SETTINGS = get_settings()

MAX_FILE_MB: int = SETTINGS.UPLOAD_MAX_FILE_BYTES // (1024 * 1024)
DEFAULT_FILE_NAME: str = "image"


def object_name(merchant_id: UUID, extension: str) -> str:
    """merchants/{merchant_id}/files/{random}{ext}: unguessable, nothing from the client in
    it, and one prefix holds everything a merchant uploaded (deleting their data on request
    is a single prefix delete)"""
    return f"merchants/{merchant_id}/files/{uuid.uuid4().hex}{extension}"


class UploadService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_files(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        self._file_service = FileService(file_repo=self._uow.repo(FileRepository))

    @staticmethod
    async def _read_image(file: UploadFile) -> tuple[str, ProcessedImage]:
        file_name: str = (file.filename or DEFAULT_FILE_NAME)[:255]

        # the size is known once the body is received; checked again after reading in
        # case the client did not send it
        if file.size is not None and file.size > SETTINGS.UPLOAD_MAX_FILE_BYTES:
            raise PayloadTooLargeError(MAX_FILE_MB, file_name)

        data: bytes = await file.read(SETTINGS.UPLOAD_MAX_FILE_BYTES + 1)
        if len(data) > SETTINGS.UPLOAD_MAX_FILE_BYTES:
            raise PayloadTooLargeError(MAX_FILE_MB, file_name)

        try:
            image: ProcessedImage = await run_in_threadpool(process_image, data)
        except NotAnImageError as exc:
            raise UnsupportedFileTypeError(file_name) from exc

        return file_name, image

    async def upload_images(
        self,
        curr_merchant: Merchant,
        files: list[UploadFile],
        uow: UnitOfWorkRepository,
        storage: MinioStorage,
    ) -> list[FileResponse]:
        """All or nothing: every file is validated before any is stored, and objects
        already stored are removed if a later step fails"""
        await self._uow_files(uow)

        merchant_id: UUID = curr_merchant.id

        if not 1 <= len(files) <= SETTINGS.UPLOAD_MAX_FILES:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "files"),
                        "msg": f"send between 1 and {SETTINGS.UPLOAD_MAX_FILES} images",
                        "type": "value_error",
                    }
                ]
            )

        images: list[tuple[str, ProcessedImage]] = [await self._read_image(f) for f in files]

        stored_objects: list[str] = []
        try:
            entities: list[FileInDB] = []
            for file_name, image in images:
                name: str = object_name(merchant_id, image.extension)
                await storage.upload_bytes(
                    SETTINGS.MINIO_BUCKET, name, image.data, image.content_type
                )
                stored_objects.append(name)
                entities.append(
                    FileInDB(
                        merchant_id=merchant_id,
                        object_name=name,
                        file_name=file_name,
                        content_type=image.content_type,
                        size=len(image.data),
                        width=image.width,
                        height=image.height,
                    )
                )

            stored: list[StoredFile] = await self._file_service.create_files(entities, commit=True)
        except Exception:
            # nothing is recorded, so nothing would ever clean these up
            for name in stored_objects:
                try:
                    await storage.delete(SETTINGS.MINIO_BUCKET, name)
                except Exception:
                    sentry_logger.error("Could not remove orphaned upload {name}", name=name)
            raise

        sentry_logger.info(
            "Merchant {merchant_id} uploaded {count} images",
            merchant_id=str(merchant_id),
            count=str(len(stored)),
        )

        # same order as the request, so clients can map their files to the ids
        return [FileResponse.model_validate(stored_file) for stored_file in stored]

    async def get_image(
        self,
        curr_merchant: Merchant,
        file_id: UUID,
        uow: UnitOfWorkRepository,
        storage: MinioStorage,
    ) -> tuple[StoredFile, bytes]:
        await self._uow_files(uow)

        # other merchants' files are reported as missing, so existence is not revealed
        stored_file: StoredFile | None = await self._file_service._get_file(
            id=file_id, merchant_id=curr_merchant.id
        )
        if not stored_file:
            raise NotFoundError("File")

        data: bytes = await storage.retrieve(SETTINGS.MINIO_BUCKET, stored_file.object_name)
        return stored_file, data

    async def delete_image(
        self,
        curr_merchant: Merchant,
        file_id: UUID,
        uow: UnitOfWorkRepository,
        storage: MinioStorage,
    ):
        """Only unattached uploads: an attached photo is evidence, so it is removed from its
        fulfillment (PATCH file_ids) first"""
        await self._uow_files(uow)

        file_repo: FileRepository = self._uow.repo(FileRepository)
        # locked so it can not be attached while it is being deleted
        stored_file: StoredFile | None = await file_repo.get_record(
            for_update=True, id=file_id, merchant_id=curr_merchant.id
        )
        if not stored_file:
            raise NotFoundError("File")
        if stored_file.fulfillment_id or stored_file.dispute_id:
            raise FileAlreadyAttachedError(str(file_id))

        # the object goes first: if the row delete then failed, the cleanup task still
        # removes the row (a missing object is fine there); the reverse order could leave an
        # object nothing points to
        await storage.delete(SETTINGS.MINIO_BUCKET, stored_file.object_name)

        try:
            await file_repo.delete(stored_file)
            await file_repo.commit()
        except Exception as exc:
            await file_repo.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while deleting file {file_id}", file_id=str(file_id))
            raise ServerError() from exc

        sentry_logger.info(
            "Merchant {merchant_id} deleted upload {file_id}",
            merchant_id=str(curr_merchant.id),
            file_id=str(file_id),
        )
