from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.models.merchants import Merchant
from app.api.models.webhook_events import WebhookEvent
from app.api.repo.base import BaseRepository


class WebhookEventRepository(BaseRepository[BaseModel, WebhookEvent]):
    model = WebhookEvent

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return WebhookEvent(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions

    async def record(
        self, merchant_id: UUID, event: str, body_hash: str, payload: dict, received_at: datetime
    ) -> tuple[UUID, bool]:
        """Stores the delivery once; returns its id and whether it still needs processing
        (new, or a retry of one that was never processed)"""
        await self._async_session.execute(
            insert(WebhookEvent)
            .values(
                merchant_id=merchant_id,
                event=event,
                body_hash=body_hash,
                payload=payload,
                received_at=received_at,
            )
            .on_conflict_do_nothing(constraint="webhook_events_merchant_body_uq")
        )
        row = (
            await self._async_session.execute(
                select(WebhookEvent.id, WebhookEvent.processed_at).where(
                    WebhookEvent.merchant_id == merchant_id, WebhookEvent.body_hash == body_hash
                )
            )
        ).one()
        return row[0], row[1] is None

    async def stamp_received(self, merchant_id: UUID, received_at: datetime):
        """The merchant's webhook is delivering"""
        await self._async_session.execute(
            update(Merchant)
            .where(Merchant.id == merchant_id)
            .values(webhook_last_received_at=received_at)
        )


class SyncWebhookEventRepository:
    """For the worker that processes stored deliveries"""

    def __init__(self, session: Session):
        self._session = session

    def get_for_update(self, event_id: UUID) -> WebhookEvent | None:
        return self._session.get(WebhookEvent, event_id, with_for_update=True)

    def mark_processed(self, event: WebhookEvent, processed_at: datetime):
        event.processed_at = processed_at
        event.error = None

    def mark_failed(self, event_id: UUID, error: str):
        self._session.execute(
            update(WebhookEvent).where(WebhookEvent.id == event_id).values(error=error[:2000])
        )
