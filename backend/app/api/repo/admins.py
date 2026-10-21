from typing import Any
from uuid import UUID

from app.api.models.admins import Admin
from app.api.repo.base import BaseRepository
from app.api.schemas.admin import AdminInDB


class AdminAccountRepository(BaseRepository[AdminInDB, Admin]):
    model = Admin

    @staticmethod
    def _entity_to_model(entity: AdminInDB) -> Admin:
        return Admin(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []
        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "email" in filters:
            filter_conditions.append(self.model.email == filters["email"])
        return filter_conditions

    async def get_by_email(self, email: str) -> Admin | None:
        return await self.get_record(email=email.lower())

    async def get_by_id(self, admin_id: UUID) -> Admin | None:
        return await self.get_record(id=admin_id)
