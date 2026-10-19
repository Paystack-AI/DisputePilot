import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.files import StoredFile
from app.api.repo.files import FileRepository
from app.api.schemas.files import FileInDB
from app.core.exceptions import ServerError


class FileService:
    def __init__(self, file_repo: FileRepository):
        self._file_repo = file_repo

    async def _get_file(self, **filters) -> StoredFile | None:
        return await self._file_repo.get_record(**filters)

    async def create_files(self, files: list[FileInDB], commit: bool = False) -> list[StoredFile]:
        try:
            stored: list[StoredFile] = self._file_repo.add_all(files)

            if commit:
                await self._file_repo.commit()
            else:
                await self._file_repo.flush()
            for stored_file in stored:
                await self._file_repo.refresh(stored_file)

            return stored
        except Exception as exc:
            if commit:
                await self._file_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating files")
            raise ServerError() from exc
