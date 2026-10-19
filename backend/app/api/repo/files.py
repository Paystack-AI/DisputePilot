from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.api.models.files import StoredFile
from app.api.repo.base import BaseRepository
from app.api.schemas.files import FileInDB


class FileRepository(BaseRepository[FileInDB, StoredFile]):
    model = StoredFile

    @staticmethod
    def _entity_to_model(entity: FileInDB) -> model:
        return StoredFile(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions

    def add_all(self, entities: list[FileInDB]) -> list[StoredFile]:
        files: list[StoredFile] = [self._entity_to_model(entity) for entity in entities]
        self._async_session.add_all(files)
        return files

    async def lock_for_merchant(self, merchant_id: UUID, file_ids: list[UUID]) -> list[StoredFile]:
        """The merchant's files among file_ids, locked so two requests can not attach the
        same file at once"""
        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.merchant_id == merchant_id, self.model.id.in_(file_ids))
            .order_by(self.model.id)
            .with_for_update()
        )
        return list(rows)

    async def for_fulfillment(
        self, fulfillment_id: UUID, for_update: bool = False
    ) -> list[StoredFile]:
        stmt = (
            select(self.model)
            .where(self.model.fulfillment_id == fulfillment_id)
            .order_by(self.model.created_at, self.model.id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list(await self._async_session.scalars(stmt))

    async def for_fulfillments(self, fulfillment_ids: list[UUID]) -> dict[UUID, list[StoredFile]]:
        """Files of several fulfillments in one query, grouped by fulfillment"""
        grouped: dict[UUID, list[StoredFile]] = defaultdict(list)
        if not fulfillment_ids:
            return grouped

        rows = await self._async_session.scalars(
            select(self.model)
            .where(self.model.fulfillment_id.in_(fulfillment_ids))
            .order_by(self.model.created_at, self.model.id)
        )
        for stored_file in rows:
            grouped[stored_file.fulfillment_id].append(stored_file)
        return grouped
