import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, or_, select, text
from sqlalchemy.orm import Session

from app.api.models.ai_memories import AiMemory, AiMemoryAccessAudit
from app.api.models.disputes import Dispute
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.base import BaseRepository


def _text(content: dict[str, Any]) -> str:
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_scope(tenant_id: UUID, merchant_id: UUID) -> None:
    """The current product maps one merchant account to one tenant."""
    if tenant_id != merchant_id:
        raise ValueError("tenant and merchant scope do not match")


async def _set_tenant_context_async(session, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def _set_tenant_context_sync(session: Session, tenant_id: UUID) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def _validate_source_async(
    session, *, merchant_id: UUID, source_type: str, source_id: str, dispute_id: UUID | None
) -> None:
    if dispute_id is not None:
        owner = await session.scalar(select(Dispute.merchant_id).where(Dispute.id == dispute_id))
        if owner != merchant_id:
            raise ValueError("dispute does not belong to merchant scope")
    source_model = {
        "evidence_revision": EvidenceRevision,
        "trust_snapshot": TrustSnapshot,
    }.get(source_type)
    if source_model is not None:
        source_uuid = UUID(source_id)
        owner = await session.scalar(
            select(source_model.merchant_id).where(source_model.id == source_uuid)
        )
        if owner != merchant_id:
            raise ValueError("memory source does not belong to merchant scope")


def _validate_source_sync(
    session: Session,
    *,
    merchant_id: UUID,
    source_type: str,
    source_id: str,
    dispute_id: UUID | None,
) -> None:
    if dispute_id is not None:
        owner = session.scalar(select(Dispute.merchant_id).where(Dispute.id == dispute_id))
        if owner != merchant_id:
            raise ValueError("dispute does not belong to merchant scope")
    source_model = {
        "trust_snapshot": TrustSnapshot,
    }.get(source_type)
    if source_model is not None:
        owner = session.scalar(
            select(source_model.merchant_id).where(source_model.id == UUID(source_id))
        )
        if owner != merchant_id:
            raise ValueError("memory source does not belong to merchant scope")


class AiMemoryRepository(BaseRepository[Any, AiMemory]):
    model = AiMemory

    @staticmethod
    def _entity_to_model(entity: Any) -> AiMemory:
        return AiMemory(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        return [
            self.model.tenant_id == filters["tenant_id"],
            self.model.merchant_id == filters["merchant_id"],
        ]

    async def _audit(
        self,
        *,
        tenant_id: UUID,
        merchant_id: UUID,
        action: str,
        memory_ids: list[UUID],
    ) -> None:
        _validate_scope(tenant_id, merchant_id)
        await _set_tenant_context_async(self._async_session, tenant_id)
        self._async_session.add(
            AiMemoryAccessAudit(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                action=action,
                memory_ids=[str(memory_id) for memory_id in memory_ids] or None,
                memory_count=len(memory_ids),
            )
        )

    async def remember(
        self,
        *,
        tenant_id: UUID,
        merchant_id: UUID,
        memory_type: str,
        source_type: str,
        source_id: str,
        content: dict[str, Any],
        occurred_at: datetime,
        dispute_id: UUID | None = None,
    ) -> AiMemory:
        """Idempotently persist one source-backed memory for a merchant."""
        _validate_scope(tenant_id, merchant_id)
        await _set_tenant_context_async(self._async_session, tenant_id)
        await _validate_source_async(
            self._async_session,
            merchant_id=merchant_id,
            source_type=source_type,
            source_id=source_id,
            dispute_id=dispute_id,
        )
        serialized = _text(content)
        memory = await self._async_session.scalar(
            select(AiMemory).where(
                AiMemory.tenant_id == tenant_id,
                AiMemory.merchant_id == merchant_id,
                AiMemory.source_type == source_type,
                AiMemory.source_id == source_id,
            )
        )
        created = memory is None
        if memory is None:
            memory = AiMemory(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                dispute_id=dispute_id,
                memory_type=memory_type,
                source_type=source_type,
                source_id=source_id,
                content=content,
                content_text=serialized,
                content_hash=_hash(serialized),
                occurred_at=occurred_at,
            )
            self._async_session.add(memory)
        elif memory.deleted_at is None:
            memory.content = content
            memory.content_text = serialized
            memory.content_hash = _hash(serialized)
            memory.occurred_at = occurred_at
            memory.dispute_id = dispute_id
        await self._async_session.flush()
        await self._audit(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            action="create" if created else "update",
            memory_ids=[memory.id],
        )
        return memory

    async def retrieve(
        self,
        *,
        tenant_id: UUID,
        merchant_id: UUID,
        dispute_id: UUID | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[AiMemory]:
        """Retrieve live memories, prioritizing query matches and then recency."""
        _validate_scope(tenant_id, merchant_id)
        await _set_tenant_context_async(self._async_session, tenant_id)
        limit = max(1, min(limit, 100))
        conditions = [
            AiMemory.tenant_id == tenant_id,
            AiMemory.merchant_id == merchant_id,
            AiMemory.deleted_at.is_(None),
        ]
        if dispute_id is not None:
            conditions.append(AiMemory.dispute_id == dispute_id)
        relevance = 0
        has_relevance = False
        if query:
            terms = [term.strip() for term in query.split() if len(term.strip()) >= 3][:8]
            matches = [AiMemory.content_text.ilike(f"%{term}%") for term in terms]
            if matches:
                relevance = case((or_(*matches), 1), else_=0)
                has_relevance = True
        order = [relevance.desc()] if has_relevance else []
        order.append(AiMemory.occurred_at.desc())
        memories = list(
            await self._async_session.scalars(
                select(AiMemory).where(and_(*conditions)).order_by(*order).limit(limit)
            )
        )
        await self._audit(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            action="retrieve",
            memory_ids=[memory.id for memory in memories],
        )
        return memories

    async def delete_memory(
        self, tenant_id: UUID, merchant_id: UUID, memory_id: UUID, reason: str
    ) -> bool:
        _validate_scope(tenant_id, merchant_id)
        await _set_tenant_context_async(self._async_session, tenant_id)
        memory = await self._async_session.scalar(
            select(AiMemory).where(
                AiMemory.id == memory_id,
                AiMemory.tenant_id == tenant_id,
                AiMemory.merchant_id == merchant_id,
            )
        )
        if memory is None:
            return False
        memory.deleted_at = datetime.now(UTC)
        memory.deletion_reason = reason[:500]
        await self._audit(
            tenant_id=tenant_id, merchant_id=merchant_id, action="delete", memory_ids=[memory_id]
        )
        return True

    async def correct_memory(
        self,
        tenant_id: UUID,
        merchant_id: UUID,
        memory_id: UUID,
        content: dict[str, Any],
        reason: str,
    ) -> AiMemory | None:
        """Create an auditable replacement and retire the old memory."""
        _validate_scope(tenant_id, merchant_id)
        await _set_tenant_context_async(self._async_session, tenant_id)
        memory = await self._async_session.scalar(
            select(AiMemory).where(
                AiMemory.id == memory_id,
                AiMemory.tenant_id == tenant_id,
                AiMemory.merchant_id == merchant_id,
            )
        )
        if memory is None or memory.deleted_at is not None:
            return None
        replacement = AiMemory(
            id=uuid4(),
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            dispute_id=memory.dispute_id,
            memory_type=memory.memory_type,
            source_type="memory_correction",
            source_id=str(memory.id),
            content=content,
            content_text=_text(content),
            content_hash=_hash(_text(content)),
            occurred_at=datetime.now(UTC),
        )
        self._async_session.add(replacement)
        await self._async_session.flush()
        memory.corrected_by_id = replacement.id
        memory.deleted_at = datetime.now(UTC)
        memory.deletion_reason = reason[:500]
        await self._audit(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            action="update",
            memory_ids=[memory_id, replacement.id],
        )
        return replacement


class SyncAiMemoryRepository:
    def __init__(self, session: Session):
        self._session = session

    def remember(self, *, tenant_id: UUID, merchant_id: UUID, **kwargs) -> AiMemory:
        _validate_scope(tenant_id, merchant_id)
        _set_tenant_context_sync(self._session, tenant_id)
        _validate_source_sync(
            self._session,
            merchant_id=merchant_id,
            source_type=kwargs["source_type"],
            source_id=kwargs["source_id"],
            dispute_id=kwargs.get("dispute_id"),
        )
        content: dict[str, Any] = kwargs["content"]
        serialized = _text(content)
        memory = self._session.scalar(
            select(AiMemory).where(
                AiMemory.tenant_id == tenant_id,
                AiMemory.merchant_id == merchant_id,
                AiMemory.source_type == kwargs["source_type"],
                AiMemory.source_id == kwargs["source_id"],
            )
        )
        created = memory is None
        if memory is None:
            memory = AiMemory(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                **kwargs,
                content_text=serialized,
                content_hash=_hash(serialized),
            )
            self._session.add(memory)
        elif memory.deleted_at is None:
            memory.content = content
            memory.content_text = serialized
            memory.content_hash = _hash(serialized)
            memory.occurred_at = kwargs["occurred_at"]
        self._session.flush()
        self._session.add(
            AiMemoryAccessAudit(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                action="create" if created else "update",
                memory_ids=[str(memory.id)],
                memory_count=1,
            )
        )
        return memory

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        merchant_id: UUID,
        dispute_id: UUID | None = None,
        limit: int = 20,
    ):
        _validate_scope(tenant_id, merchant_id)
        _set_tenant_context_sync(self._session, tenant_id)
        conditions = [
            AiMemory.tenant_id == tenant_id,
            AiMemory.merchant_id == merchant_id,
            AiMemory.deleted_at.is_(None),
        ]
        if dispute_id is not None:
            conditions.append(AiMemory.dispute_id == dispute_id)
        memories = list(
            self._session.scalars(
                select(AiMemory)
                .where(and_(*conditions))
                .order_by(AiMemory.occurred_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        )
        self._session.add(
            AiMemoryAccessAudit(
                tenant_id=tenant_id,
                merchant_id=merchant_id,
                action="retrieve",
                memory_ids=[str(memory.id) for memory in memories] or None,
                memory_count=len(memories),
            )
        )
        return memories
