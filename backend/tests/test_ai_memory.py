from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.api.models.ai_memories import AiMemoryAccessAudit
from app.api.models.merchants import Merchant
from app.api.repo.ai_memory import AiMemoryRepository

SessionMaker = async_sessionmaker[AsyncSession]


@pytest.mark.asyncio
async def test_memory_persists_retrieves_beyond_five_and_is_tenant_scoped(
    session_maker: SessionMaker,
):
    merchant_id = uuid4()
    other_merchant_id = uuid4()
    async with session_maker() as session:
        first = Merchant(id=merchant_id, business_name="Memory Merchant")
        other = Merchant(id=other_merchant_id, business_name="Other Merchant")
        session.add_all([first, other])
        await session.flush()
        repo = AiMemoryRepository(session)
        now = datetime.now(UTC)
        for index in range(7):
            await repo.remember(
                tenant_id=merchant_id,
                merchant_id=merchant_id,
                memory_type="manual_note",
                source_type="manual_note",
                source_id=f"revision-{index}",
                content={"narrative": f"revision-{index}"},
                occurred_at=now - timedelta(minutes=index),
            )
        await repo.remember(
            tenant_id=other_merchant_id,
            merchant_id=other_merchant_id,
            memory_type="manual_note",
            source_type="manual_note",
            source_id="other-revision",
            content={"narrative": "private other merchant"},
            occurred_at=now,
        )
        await session.commit()

    async with session_maker() as session:
        memories = await AiMemoryRepository(session).retrieve(
            tenant_id=merchant_id, merchant_id=merchant_id, query="revision", limit=20
        )
        assert len(memories) == 7
        assert all(item.merchant_id == merchant_id for item in memories)
        assert all(item.content["narrative"] != "private other merchant" for item in memories)
        audits = list(await session.scalars(select(AiMemoryAccessAudit)))
        assert audits
        assert all(audit.tenant_id == merchant_id for audit in audits)
        assert not hasattr(audits[0], "content")

        with pytest.raises(ValueError):
            await AiMemoryRepository(session).retrieve(
                tenant_id=merchant_id, merchant_id=other_merchant_id
            )


@pytest.mark.asyncio
async def test_memory_correction_and_deletion_are_auditable(session_maker: SessionMaker):
    merchant_id = uuid4()
    async with session_maker() as session:
        session.add(Merchant(id=merchant_id, business_name="Correction Merchant"))
        await session.flush()
        repo = AiMemoryRepository(session)
        original = await repo.remember(
            tenant_id=merchant_id,
            merchant_id=merchant_id,
            memory_type="manual_note",
            source_type="manual_note",
            source_id="snapshot-1",
            content={"state": "building"},
            occurred_at=datetime.now(UTC),
        )
        await session.flush()
        replacement = await repo.correct_memory(
            merchant_id,
            merchant_id,
            original.id,
            {"state": "verified"},
            "verified correction",
        )
        assert replacement is not None
        await session.commit()

    async with session_maker() as session:
        memories = await AiMemoryRepository(session).retrieve(
            tenant_id=merchant_id, merchant_id=merchant_id
        )
        assert [item.content for item in memories] == [{"state": "verified"}]
        assert memories[0].source_type == "memory_correction"
