from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileInDB(BaseModel):
    merchant_id: UUID
    object_name: str
    file_name: str
    content_type: str
    size: int
    width: int
    height: int


class FileResponse(BaseModel):
    """An uploaded image. The storage location is internal: clients use the id, and read
    the image from GET /uploads/{id}"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    content_type: str
    size: int
    width: int
    height: int
    created_at: datetime


class UploadResult(BaseModel):
    # in the order the files were sent
    files: list[FileResponse]
