"""The trust half of the backend <-> ai contract: the jobs the backend sends, and what it
does with the answers."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.ai_memories import AiMemory
from app.api.models.enums import DisputeStatus, TrustState
from app.api.models.transactions import Transaction
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.services import trust_ai
from app.api.services.ai_streams import StreamMessage
from app.api.services.events import stream_key
from app.worker.services.trust import TRUST_EXPLAIN, TRUST_STATE_CHANGE, recompute_trust_profile
from app.worker.tasks.trust import recompute_trust
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import merchant_id
from tests.test_trust import _ids, _shop

SessionMaker = async_sessionmaker[AsyncSession]


def _result(event: str, job_id: str, payload: dict) -> StreamMessage:
    return StreamMessage(
        id="1-0",
        event=event,
        job_id=job_id,
        version="1",
        payload=payload,
        created_at="",
        deliveries=1,
    )


class TestJobsSent:
    @pytest.mark.asyncio
    async def test_first_run_asks_for_an_explanation(self, sync_db: Session):
        merchant = _shop(sync_db)

        outcome = recompute_trust_profile(sync_db, merchant.id, "scheduled")

        (job,) = outcome.ai_jobs
        assert job.event == TRUST_EXPLAIN
        assert job.payload["merchantId"] == str(merchant.id)
        assert job.payload["currentState"] == "verified"
        assert set(job.payload["signals"]) == {
            "reconciliation_rate",
            "fulfillment_rate",
            "dispute_rate",
            "dispute_win_rate",
            "avg_response_time",
            "evidence_readiness",
        }
        assert job.payload["signals"]["dispute_win_rate"] is None
        assert job.payload["sample"] == {"payments_30d": 30, "days_on_platform": 60}
        assert job.payload["policyThresholds"]["verified"]["reconciliation_rate"] == (
            "at least 80%"
        )
        profile = sync_db.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant.id)
        )
        assert profile.explain_job_id == job.job_id
        assert job.payload["memory"]["recentMemories"]

    @pytest.mark.asyncio
    async def test_a_state_change_asks_for_a_summary(self, sync_db: Session):
        merchant = _shop(sync_db)
        recompute_trust_profile(sync_db, merchant.id, "scheduled")
        payment = sync_db.scalar(
            select(Transaction).where(Transaction.merchant_id == merchant.id).limit(1)
        )
        sync_db.add(
            Dispute(
                merchant_id=merchant.id,
                transaction_id=payment.id,
                paystack_dispute_id=next(_ids),
                paystack_reference=payment.paystack_reference,
                amount=5000,
                due_at=datetime.now(UTC),
                status=DisputeStatus.LOST,
            )
        )
        sync_db.commit()

        outcome = recompute_trust_profile(sync_db, merchant.id, "dispute_resolved")

        events = [job.event for job in outcome.ai_jobs]
        assert events == [TRUST_EXPLAIN, TRUST_STATE_CHANGE]
        change = outcome.ai_jobs[1]
        assert change.payload["previousState"] == "verified"
        assert change.payload["newState"] == "building"
        assert change.payload["signalDiff"]["dispute_win_rate"] == {"before": None, "after": 0.0}
        # keyed by the snapshot it describes
        snapshot = sync_db.get(TrustSnapshot, UUID(change.job_id))
        assert snapshot.state == TrustState.BUILDING

    @pytest.mark.asyncio
    async def test_unchanged_sends_nothing(self, sync_db: Session):
        merchant = _shop(sync_db)
        recompute_trust_profile(sync_db, merchant.id, "scheduled")
        assert recompute_trust_profile(sync_db, merchant.id, "scheduled").ai_jobs == ()

    @pytest.mark.asyncio
    async def test_task_sends_them_after_commit(self, sync_db: Session, trust_ai_jobs: MagicMock):
        merchant = _shop(sync_db)
        with (
            patch("app.worker.tasks.trust.sync_session", lambda: nullcontext(sync_db)),
            patch("app.worker.tasks.trust.publish"),
        ):
            recompute_trust(str(merchant.id), "scheduled")

        (call,) = trust_ai_jobs.call_args_list
        assert call.args[1] == TRUST_EXPLAIN
        assert call.args[2]["merchantId"] == str(merchant.id)


@pytest.fixture
def ai(session_maker: SessionMaker, test_redis_client: Redis):
    with (
        patch.object(trust_ai, "session_factory", session_maker),
        patch.object(trust_ai, "redis_factory", lambda: test_redis_client),
    ):
        yield


async def _profile(session_maker: SessionMaker, merchant: UUID) -> TrustProfile:
    async with session_maker() as session:
        return await session.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant)
        )


class TestAnswers:
    @pytest.mark.asyncio
    async def test_explanation_and_actions(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        test_redis_client: Redis,
        ai,
    ):
        await async_client.get("/trust/profile", headers=auth_headers)
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        async with session_maker() as session:
            await session.execute(
                update(TrustProfile)
                .where(TrustProfile.merchant_id == merchant)
                .values(explain_job_id="job-2")
            )
            await session.commit()

        answer: dict = {
            "merchantId": str(merchant),
            "explanation": "  You are Building: fulfillment is at 55%; verified needs 70%.  ",
            "recommendations": [
                {
                    "action": "Log fulfillment with a photo for paid orders",
                    "impact_description": "Fulfillment is at 55%; verified needs 70%",
                    "affected_signal": "fulfillment_rate",
                    "extra": "dropped",
                },
                {"impact_description": "no action: dropped"},
            ],
        }
        # an answer to an older job changes nothing
        await trust_ai.on_trust_explained(_result(trust_ai.TRUST_EXPLAINED, "job-1", answer))
        assert (await _profile(session_maker, merchant)).explanation is None

        await trust_ai.on_trust_explained(_result(trust_ai.TRUST_EXPLAINED, "job-2", answer))

        profile = await _profile(session_maker, merchant)
        assert profile.explanation == (
            "You are Building: fulfillment is at 55%; verified needs 70%."
        )
        assert profile.explain_job_id is None
        async with session_maker() as session:
            memory = await session.scalar(
                select(AiMemory).where(
                    AiMemory.merchant_id == merchant,
                    AiMemory.source_type == "trust_explanation_job",
                )
            )
        assert memory is not None
        assert memory.content["explanation"].startswith("You are Building")
        events = await test_redis_client.xrange(stream_key(merchant))
        assert events[-1][1]["type"] == "trust.explained"
        assert json.loads(events[-1][1]["data"])["actions"] == 1

        data: dict = (await async_client.get("/trust/actions", headers=auth_headers)).json()["data"]
        assert data["actions"] == [
            {
                "action": "Log fulfillment with a photo for paid orders",
                "impact_description": "Fulfillment is at 55%; verified needs 70%",
                "affected_signal": "fulfillment_rate",
            }
        ]
        assert data["generated_at"]
        profile_data: dict = (
            await async_client.get("/trust/profile", headers=auth_headers)
        ).json()["data"]
        assert profile_data["explanation"].startswith("You are Building")

    @pytest.mark.asyncio
    async def test_actions_empty_before_any_answer(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        data: dict = (await async_client.get("/trust/actions", headers=auth_headers)).json()["data"]
        assert data == {"actions": [], "generated_at": None}

    @pytest.mark.asyncio
    async def test_state_change_summary_in_history(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker, ai
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        async with session_maker() as session:
            snapshot = TrustSnapshot(
                merchant_id=merchant,
                state=TrustState.BUILDING,
                internal_score=60,
                signals={},
                reason="fulfillment_logged",
            )
            session.add(snapshot)
            await session.commit()
            snapshot_id: UUID = snapshot.id

        await trust_ai.on_state_change_summarized(
            _result(
                trust_ai.STATE_CHANGE_SUMMARIZED,
                str(snapshot_id),
                {
                    "merchantId": str(merchant),
                    "summary": "You moved to Building as fulfillment rose to 45%.",
                },
            )
        )
        # another merchant's id in the answer is ignored
        await trust_ai.on_state_change_summarized(
            _result(
                trust_ai.STATE_CHANGE_SUMMARIZED,
                str(snapshot_id),
                {"merchantId": "someone-else", "summary": "overwritten"},
            )
        )

        data: dict = (await async_client.get("/trust/history", headers=auth_headers)).json()["data"]
        assert data["changes"][0]["summary"] == (
            "You moved to Building as fulfillment rose to 45%."
        )
        assert data["points"][0]["summary"] == data["changes"][0]["summary"]

    @pytest.mark.asyncio
    async def test_invalid_answers_are_ignored(self, ai):
        await trust_ai.on_trust_explained(
            _result(trust_ai.TRUST_EXPLAINED, "job", {"merchantId": None, "explanation": "x"})
        )
        await trust_ai.on_state_change_summarized(
            _result(trust_ai.STATE_CHANGE_SUMMARIZED, "not-a-uuid", {"summary": "x"})
        )
