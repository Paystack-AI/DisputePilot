from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Row, Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models.base import Base

Entity = TypeVar("Entity", bound=BaseModel)
SqlalchemyModel = TypeVar("SqlalchemyModel", bound=Base)

LIKE_ESCAPE: str = "\\"


def contains_pattern(term: str) -> str:
    """ILIKE pattern matching term anywhere, with % and _ in the term taken literally;
    use with escape=LIKE_ESCAPE"""
    escaped: str = (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


class BaseRepository(ABC, Generic[Entity, SqlalchemyModel]):
    def __init__(self, async_session: AsyncSession = None):
        self._async_session = async_session

    model: type[SqlalchemyModel]

    @property
    def async_session(self):
        return self._async_session

    @async_session.setter
    def async_session(self, session):
        self._async_session = session

    def add(self, entity: Entity | None = None, model: SqlalchemyModel | None = None):
        if not model:
            model: SqlalchemyModel = self._entity_to_model(entity)
        self._async_session.add(model)
        return model

    async def flush(self):
        await self._async_session.flush()

    async def refresh(self, model: SqlalchemyModel):
        await self._async_session.refresh(model)

    async def commit(self):
        await self._async_session.commit()

    async def rollback(self):
        await self._async_session.rollback()

    async def delete(self, model: SqlalchemyModel):
        await self._async_session.delete(model)

    async def get_record(self, for_update: bool = False, **filters) -> SqlalchemyModel | None:
        """for_update locks the row until the transaction ends, so concurrent
        requests acting on the same record run one after the other"""
        filter_conditions: list[Any] = self._get_filters(**filters)

        stmt = select(self.model).where(*filter_conditions)
        if for_update:
            stmt = stmt.with_for_update()

        res = await self._async_session.execute(stmt)
        return res.scalar()

    async def _paginate(
        self, stmt: Select, count_stmt: Select, page: int, limit: int
    ) -> tuple[list[Row], int]:
        """One page of stmt and the total matching it, in one query: the total rides on each
        row as a window count. Only a page past the end (no rows to carry it) runs count_stmt.
        Each row gets total_count appended as its last column"""
        rows = (
            await self._async_session.execute(
                stmt.add_columns(func.count().over().label("total_count"))
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()

        if rows:
            return rows, rows[0].total_count
        if page == 1:
            return [], 0
        return [], await self._async_session.scalar(count_stmt)

    async def update_records(self, fields_to_update: dict[str, Any], **filters):
        filter_conditions: list[Any] = self._get_filters(**filters)
        await self._async_session.execute(
            update(self.model).values(fields_to_update).where(*filter_conditions)
        )

    @abstractmethod
    def _entity_to_model(self, entity: Entity) -> SqlalchemyModel:
        raise NotImplementedError("Subclasses must implement _entity_to_model method")

    @abstractmethod
    def _get_filters(self, **filters) -> list[Any]:
        return []
