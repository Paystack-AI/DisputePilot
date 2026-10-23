import itertools
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeCategory,
    DisputeStatus,
    EvidenceChange,
    EvidenceState,
    EvidenceStep,
    GenerationSource,
    ReconciliationStatus,
)
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.ai_memories import AiMemory
from app.api.models.files import StoredFile
from app.api.models.merchants import Merchant
from app.api.services import dispute_ai
from app.api.services.ai_streams import StreamMessage
from app.api.services.events import stream_key
from app.core.config import get_settings
from app.worker.tasks.dispute_submission import accept_dispute, submit_dispute
from app.worker.tasks.disputes import poll_disputes
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_fulfillment, add_transaction, merchant_id

SETTINGS = get_settings()
SessionMaker = async_sessionmaker[AsyncSession]
_paystack_ids = itertools.count(700_000)


async def _merchant(session_maker: SessionMaker) -> UUID:
    return await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])


async def _dispute(
    session_maker: SessionMaker,
    merchant: UUID,
    transaction_id: UUID | None = None,
    due_in: timedelta = timedelta(hours=12),
    reason: str = "Customer complained about debit without value",
    **fields,
) -> UUID:
    transaction_id = transaction_id or await add_transaction(session_maker, merchant)
    async with session_maker() as session:
        dispute = Dispute(
            merchant_id=merchant,
            transaction_id=transaction_id,
            paystack_dispute_id=next(_paystack_ids),
            paystack_reference="ref",
            amount=4500000,
            due_at=datetime.now(UTC) + due_in,
            reason_raw=reason,
            **{
                "status": DisputeStatus.PENDING,
                "paystack_status": "awaiting-merchant-feedback",
                **fields,
            },
        )
        session.add(dispute)
        await session.commit()
        return dispute.id


async def _get(session_maker: SessionMaker, dispute_id: UUID) -> Dispute:
    async with session_maker() as session:
        return await session.get(Dispute, dispute_id)


@pytest.fixture
def ai(session_maker: SessionMaker, test_redis_client: Redis):
    """The chain's handlers on the test database and redis"""
    with (
        patch.object(dispute_ai, "session_factory", session_maker),
        patch.object(dispute_ai, "redis_factory", lambda: test_redis_client),
    ):
        yield


@pytest.fixture
def queued_responses():
    with (
        patch.object(submit_dispute, "apply_async") as submit,
        patch.object(accept_dispute, "apply_async") as accept,
        patch.object(poll_disputes, "apply_async") as poll,
    ):
        yield {"submit": submit, "accept": accept, "poll": poll}


async def _requests(redis: Redis) -> list[dict]:
    """What the backend sent to the ai worker"""
    entries = await redis.xrange(SETTINGS.AI_REQUEST_STREAM)
    return [
        {"event": f["event"], "job_id": f["job_id"], "payload": json.loads(f["payload"])}
        for _, f in entries
    ]


async def _events(redis: Redis, merchant: UUID) -> list[tuple[str, dict]]:
    entries = await redis.xrange(stream_key(merchant))
    return [(f["type"], json.loads(f["data"])) for _, f in entries]


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


async def _ready(session_maker: SessionMaker, merchant: UUID, **fields) -> UUID:
    """A dispute with a generated draft, ready to edit or submit"""
    return await _dispute(
        session_maker,
        merchant,
        category=DisputeCategory.CHARGEBACK_NO_VALUE,
        evidence_state=EvidenceState.READY,
        evidence_narrative="The order was delivered.",
        evidence_conclusion="Please resolve in the merchant's favour.",
        evidence_version=1,
        generation_source=GenerationSource.AI,
        status=DisputeStatus.EVIDENCE_GENERATED,
        **fields,
    )


class TestReads:
    @pytest.mark.asyncio
    async def test_list_with_urgency_filter(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        critical: UUID = await _dispute(session_maker, merchant, due_in=timedelta(hours=2))
        await _dispute(session_maker, merchant, due_in=timedelta(hours=6))
        await _dispute(session_maker, merchant, due_in=timedelta(hours=20))

        res: Response = await async_client.get(
            "/disputes?urgency=critical&sort=due_at", headers=auth_headers
        )

        assert res.status_code == 200, res.text
        body: dict = res.json()
        assert [d["id"] for d in body["data"]] == [str(critical)]
        assert body["data"][0]["urgency"] == "critical"
        assert body["data"][0]["reason"] == "Customer complained about debit without value"
        assert "server_time" in body["meta"]

        res = await async_client.get("/disputes", headers=auth_headers)
        assert {d["urgency"] for d in res.json()["data"]} == {"critical", "warning", "safe"}

    @pytest.mark.asyncio
    async def test_detail_builds_the_evidence_document(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        order = (
            await async_client.post(
                "/orders",
                json={"amount": 4500000, "order_number": "A-9", "description": "Blue sneakers"},
                headers=auth_headers,
            )
        ).json()["data"]
        transaction = await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )
        await add_fulfillment(session_maker, merchant, UUID(order["id"]))
        dispute_id: UUID = await _dispute(session_maker, merchant, transaction)

        res: Response = await async_client.get(f"/disputes/{dispute_id}", headers=auth_headers)

        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        evidence: dict = data["evidence"]
        assert evidence["header"]["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert evidence["transaction_receipt"]["amount"] == 4500000
        assert evidence["order_details"]["description"] == "Blue sneakers"
        assert evidence["fulfillment_evidence"][0]["tracking_number"] == "GIG-0012"
        assert evidence["narrative"] is None
        assert evidence["editable"] == ["narrative", "supporting_documents", "conclusion"]
        # no photo yet: listed for the merchant
        assert "A delivery photo" in evidence["missing_evidence"]
        assert data["allowed_actions"] == ["generate_evidence", "edit_evidence", "accept"]
        assert data["readiness"]["score"] > 0

    @pytest.mark.asyncio
    async def test_other_merchants_dispute_is_missing(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.get(f"/disputes/{uuid4()}", headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_stats(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        now: datetime = datetime.now(UTC)
        await _dispute(session_maker, merchant)
        await _dispute(session_maker, merchant, status=DisputeStatus.WON, submitted_at=now)
        await _dispute(session_maker, merchant, status=DisputeStatus.AUTO_ACCEPTED)

        data: dict = (await async_client.get("/disputes/stats", headers=auth_headers)).json()[
            "data"
        ]

        assert (data["total"], data["open"], data["won"], data["auto_accepted"]) == (3, 1, 1, 1)
        assert data["win_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_sync_is_queued(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_responses: dict,
    ):
        res: Response = await async_client.post("/disputes/sync", headers=auth_headers)
        assert res.status_code == 422  # no key connected

        merchant: UUID = await _merchant(session_maker)
        async with session_maker() as session:
            await session.execute(
                update(Merchant).where(Merchant.id == merchant).values(paystack_secret_key="x")
            )
            await session.commit()
        res = await async_client.post("/disputes/sync", headers=auth_headers)
        assert res.status_code == 202
        queued_responses["poll"].assert_called_once()


class TestEvidenceChain:
    @pytest.mark.asyncio
    async def test_full_chain(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        test_redis_client: Redis,
        ai,
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(session_maker, merchant)

        res: Response = await async_client.post(
            f"/disputes/{dispute_id}/generate-evidence", headers=auth_headers
        )
        assert res.status_code == 202, res.text
        assert res.json()["data"]["evidence_step"] == "classify"

        (classify,) = await _requests(test_redis_client)
        assert classify["event"] == dispute_ai.CLASSIFY
        assert classify["payload"]["messagesBody"] == (
            "Customer complained about debit without value"
        )

        await dispute_ai.on_classified(
            _result(
                dispute_ai.CLASSIFIED,
                classify["job_id"],
                {
                    "disputeId": str(dispute_id),
                    "category": "chargeback_no_value",
                    "confidence": 0.92,
                    "submissionFlow": "chargeback_flow",
                    "evidenceStrategy": ["delivery_photo"],
                    "specialInstructions": None,
                },
            )
        )
        generate = (await _requests(test_redis_client))[1]
        assert generate["event"] == dispute_ai.GENERATE
        assert generate["payload"]["category"] == "chargeback_no_value"
        assert generate["payload"]["transaction"]["amount"] == 4500000
        assert generate["payload"]["reconciliationStatus"] == {
            "status": "unmatched",
            "tier": None,
            "confidence": None,
            "reconciled_at": None,
        }

        await dispute_ai.on_generated(
            _result(
                dispute_ai.GENERATED,
                generate["job_id"],
                {
                    "disputeId": str(dispute_id),
                    "narrative": "On 1 May the customer paid. The order was delivered.",
                    "missingEvidence": ["delivery photo"],
                    "evidenceItemsReferenced": ["transaction_receipt"],
                },
            )
        )
        score = (await _requests(test_redis_client))[2]
        assert score["event"] == dispute_ai.SCORE

        await dispute_ai.on_scored(
            _result(
                dispute_ai.SCORED,
                score["job_id"],
                {
                    "disputeId": str(dispute_id),
                    "overallScore": 72,
                    # models may answer with fractions; the api shows whole numbers
                    "dimensionScores": {"completeness": 70.4},
                    "suggestions": ["Add a delivery photo"],
                    "readyToSubmit": True,
                },
            )
        )

        dispute: Dispute = await _get(session_maker, dispute_id)
        assert dispute.evidence_state == EvidenceState.READY
        assert dispute.status == DisputeStatus.EVIDENCE_GENERATED
        assert dispute.evidence_version == 1
        assert dispute.generation_source == GenerationSource.AI
        # the ai's narrative with the template conclusion (none was sent)
        assert dispute.evidence_conclusion.startswith("Based on the evidence provided")

        events = await _events(test_redis_client, merchant)
        assert [t for t, _ in events] == [
            "evidence.progress",
            "evidence.progress",
            "evidence.progress",
            "evidence.ready",
        ]
        ready: dict = events[-1][1]["evidence"]
        assert ready["narrative"].startswith("On 1 May")
        assert ready["quality"] == {
            "score": 72,
            "label": "moderate",
            "dimension_scores": {"completeness": 70},
            "suggestions": ["Add a delivery photo"],
            "ready_to_submit": True,
        }
        async with session_maker() as session:
            revision = await session.scalar(select(EvidenceRevision))
            memory = await session.scalar(select(AiMemory).where(AiMemory.dispute_id == dispute_id))
        assert (revision.version, revision.change) == (1, EvidenceChange.GENERATED)
        assert memory is not None
        assert memory.content["narrative"].startswith("On 1 May")

    @pytest.mark.asyncio
    async def test_stale_result_is_ignored(
        self, session_maker: SessionMaker, test_redis_client: Redis, ai, login
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(
            session_maker,
            merchant,
            evidence_state=EvidenceState.GENERATING,
            evidence_step=EvidenceStep.CLASSIFY,
            ai_job_id="current-job",
            evidence_step_started_at=datetime.now(UTC),
        )

        await dispute_ai.on_classified(
            _result(
                dispute_ai.CLASSIFIED,
                "older-job",
                {"disputeId": str(dispute_id), "category": "fraud"},
            )
        )

        dispute: Dispute = await _get(session_maker, dispute_id)
        assert dispute.category is None
        assert await _requests(test_redis_client) == []

    @pytest.mark.asyncio
    async def test_generate_error_falls_back_to_template(
        self, session_maker: SessionMaker, test_redis_client: Redis, ai, login
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(
            session_maker,
            merchant,
            category=DisputeCategory.CHARGEBACK_NO_VALUE,
            evidence_state=EvidenceState.GENERATING,
            evidence_step=EvidenceStep.GENERATE,
            ai_job_id="job-1",
            evidence_step_started_at=datetime.now(UTC),
        )

        await dispute_ai.on_error(
            _result(
                dispute_ai.AI_ERROR,
                "job-1",
                {"disputeId": str(dispute_id), "error": "llm timeout", "retryCount": 1},
            )
        )

        dispute: Dispute = await _get(session_maker, dispute_id)
        assert dispute.evidence_state == EvidenceState.READY
        assert dispute.generation_source == GenerationSource.TEMPLATE
        assert "made a payment of NGN 45,000.00" in dispute.evidence_narrative
        assert dispute.evidence_quality_score is None
        events = await _events(test_redis_client, merchant)
        assert events[-1][0] == "evidence.ready"
        assert events[-1][1]["evidence"]["generation_source"] == "template"

    @pytest.mark.asyncio
    async def test_classify_timeout_uses_keywords(
        self, session_maker: SessionMaker, test_redis_client: Redis, ai, login
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(
            session_maker,
            merchant,
            reason="Cardholder reports unauthorized transaction on their card",
            evidence_state=EvidenceState.GENERATING,
            evidence_step=EvidenceStep.CLASSIFY,
            ai_job_id="job-1",
            evidence_step_started_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        assert await dispute_ai.sweep_timeouts() == 1

        dispute: Dispute = await _get(session_maker, dispute_id)
        assert dispute.category == DisputeCategory.FRAUD
        assert dispute.submission_flow.value == "fraud_flow"
        # the chain carries on with the narrative
        assert dispute.evidence_step == EvidenceStep.GENERATE
        assert [r["event"] for r in await _requests(test_redis_client)] == [dispute_ai.GENERATE]


class TestEditEvidence:
    @pytest.mark.asyncio
    async def test_edit_with_reason_and_version(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _ready(session_maker, merchant)

        res: Response = await async_client.put(
            f"/disputes/{dispute_id}/evidence",
            json={"version": 1, "narrative": "Delivered on 2 May.", "reason": "Fixed the date"},
            headers=auth_headers,
        )

        assert res.status_code == 200, res.text
        evidence: dict = res.json()["data"]["evidence"]
        assert (evidence["version"], evidence["narrative"]) == (2, "Delivered on 2 May.")
        async with session_maker() as session:
            revision = await session.scalar(
                select(EvidenceRevision).where(EvidenceRevision.dispute_id == dispute_id)
            )
        assert (revision.change, revision.reason) == (EvidenceChange.TEXT, "Fixed the date")

        # an edit made on version 1 again is stale now
        res = await async_client.put(
            f"/disputes/{dispute_id}/evidence",
            json={"version": 1, "conclusion": "Thanks.", "reason": "Shorter"},
            headers=auth_headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "EVIDENCE_VERSION_CONFLICT"
        assert res.json()["error"]["details"]["current_version"] == "2"

    @pytest.mark.asyncio
    async def test_attach_documents_with_captions(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _ready(session_maker, merchant)
        async with session_maker() as session:
            upload = StoredFile(
                merchant_id=merchant,
                object_name=f"{merchant}/{uuid4()}.jpg",
                file_name="chat.jpg",
                content_type="image/jpeg",
                size=10,
                width=10,
                height=10,
            )
            session.add(upload)
            await session.commit()
            file_id: UUID = upload.id

        res: Response = await async_client.put(
            f"/disputes/{dispute_id}/evidence",
            json={
                "version": 1,
                "documents": [{"file_id": str(file_id), "caption": "Customer's thanks on chat"}],
                "reason": "Added the chat screenshot",
            },
            headers=auth_headers,
        )

        assert res.status_code == 200, res.text
        documents: list = res.json()["data"]["evidence"]["supporting_documents"]
        assert documents == [
            {
                "file_id": str(file_id),
                "file_name": "chat.jpg",
                "caption": "Customer's thanks on chat",
                "source": "merchant",
            }
        ]
        async with session_maker() as session:
            change = await session.scalar(select(EvidenceRevision.change))
        assert change == EvidenceChange.DOCUMENTS

        # removing it detaches the upload (cleaned up later)
        res = await async_client.put(
            f"/disputes/{dispute_id}/evidence",
            json={"version": 2, "documents": [], "reason": "Wrong screenshot"},
            headers=auth_headers,
        )
        assert res.json()["data"]["evidence"]["supporting_documents"] == []
        async with session_maker() as session:
            assert (await session.get(StoredFile, file_id)).dispute_id is None

    @pytest.mark.asyncio
    async def test_no_edits_while_generating(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(
            session_maker, merchant, evidence_state=EvidenceState.GENERATING
        )
        res: Response = await async_client.put(
            f"/disputes/{dispute_id}/evidence",
            json={"version": 0, "narrative": "Mine", "reason": "Writing it myself"},
            headers=auth_headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["details"]["reason"] == "evidence_generating"


class TestRespond:
    @pytest.mark.asyncio
    async def test_submit_freezes_the_document(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_responses: dict,
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _ready(session_maker, merchant)

        stale: Response = await async_client.post(
            f"/disputes/{dispute_id}/submit", json={"version": 5}, headers=auth_headers
        )
        assert stale.status_code == 409

        res: Response = await async_client.post(
            f"/disputes/{dispute_id}/submit", json={"version": 1}, headers=auth_headers
        )

        assert res.status_code == 202, res.text
        assert res.json()["data"]["submission_state"] == "submitting"
        queued_responses["submit"].assert_called_once()
        async with session_maker() as session:
            revision = await session.scalar(
                select(EvidenceRevision).where(EvidenceRevision.change == EvidenceChange.SUBMITTED)
            )
        assert revision.snapshot["document"]["narrative"] == "The order was delivered."
        assert revision.snapshot["submission_flow"] == "chargeback_flow"

        # a second response while the first runs is refused
        res = await async_client.post(
            f"/disputes/{dispute_id}/accept", json={}, headers=auth_headers
        )
        assert res.status_code == 409
        assert res.json()["error"]["details"]["reason"] == "response_in_progress"

    @pytest.mark.asyncio
    async def test_fraud_needs_customer_details(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_responses: dict,
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _ready(session_maker, merchant)
        async with session_maker() as session:
            await session.execute(
                update(Dispute)
                .where(Dispute.id == dispute_id)
                .values(category=DisputeCategory.FRAUD)
            )
            await session.commit()

        res: Response = await async_client.post(
            f"/disputes/{dispute_id}/submit", json={"version": 1}, headers=auth_headers
        )

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "FRAUD_EVIDENCE_INCOMPLETE"
        assert "customer_phone" in res.json()["error"]["details"]["missing"]
        queued_responses["submit"].assert_not_called()

    @pytest.mark.asyncio
    async def test_accept(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_responses: dict,
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(session_maker, merchant)

        res: Response = await async_client.post(
            f"/disputes/{dispute_id}/accept",
            json={"message": "We refunded the duplicate charge."},
            headers=auth_headers,
        )

        assert res.status_code == 202, res.text
        assert res.json()["data"]["submission_state"] == "accepting"
        kwargs: dict = queued_responses["accept"].call_args.kwargs["kwargs"]
        assert kwargs == {
            "dispute_id": str(dispute_id),
            "message": "We refunded the duplicate charge.",
        }

    @pytest.mark.asyncio
    async def test_no_response_after_the_deadline(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_responses: dict,
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(session_maker, merchant, due_in=timedelta(hours=-1))
        res: Response = await async_client.post(
            f"/disputes/{dispute_id}/accept", json={}, headers=auth_headers
        )
        assert res.status_code == 409
        assert res.json()["error"]["details"]["reason"] == "deadline_passed"

    @pytest.mark.asyncio
    async def test_pdf_missing_before_submission(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(session_maker, merchant)
        res: Response = await async_client.get(
            f"/disputes/{dispute_id}/evidence-pdf", headers=auth_headers
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_error_duplicate_recommends_accepting(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        async with session_maker() as session:
            customer = Customer(merchant_id=merchant, email="ada@example.com")
            session.add(customer)
            await session.commit()
            customer_id: UUID = customer.id
        now: datetime = datetime.now(UTC)
        await add_transaction(session_maker, merchant, customer_id=customer_id, paid_at=now)
        charged_twice: UUID = await add_transaction(
            session_maker, merchant, customer_id=customer_id, paid_at=now + timedelta(minutes=2)
        )
        dispute_id: UUID = await _dispute(
            session_maker, merchant, charged_twice, category=DisputeCategory.ADMIN_ERROR
        )

        data: dict = (
            await async_client.get(f"/disputes/{dispute_id}", headers=auth_headers)
        ).json()["data"]

        assert data["recommendation"] == "accept"


class TestTemplates:
    def test_keyword_classifier(self):
        from app.api.services.evidence_templates import classify_by_keywords

        assert classify_by_keywords("Customer was charged twice")[0] == (
            DisputeCategory.ADMIN_ERROR
        )
        assert classify_by_keywords("goods received were different from the order")[0] == (
            DisputeCategory.CHARGEBACK_NOT_AS_DESCRIBED
        )
        # fraud wins when both appear
        assert classify_by_keywords("unauthorized and not received")[0] == DisputeCategory.FRAUD
        category, confidence = classify_by_keywords("customer dispute")
        assert (category, confidence) == (DisputeCategory.CHARGEBACK_NO_VALUE, 0.3)


async def _order_id(session_maker: SessionMaker, merchant: UUID) -> str:
    from app.api.models.enums import OrderSource
    from app.api.models.orders import Order

    async with session_maker() as session:
        order = Order(
            merchant_id=merchant, amount=4500000, currency="NGN", source=OrderSource.WEBSITE
        )
        session.add(order)
        await session.commit()
        return str(order.id)


class TestQueryCounts:
    """Each read runs a fixed number of queries, whatever the data"""

    @staticmethod
    async def _count(session_maker: SessionMaker, call) -> int:
        from sqlalchemy import event

        from app.api.repo.uow import UnitOfWorkRepository

        statements: list = []
        async with session_maker() as session:
            event.listen(
                session.sync_session, "do_orm_execute", lambda state: statements.append(state)
            )
            merchant = await session.get(Merchant, await _merchant(session_maker))
            statements.clear()
            await call(merchant, UnitOfWorkRepository(session))
        return len(statements)

    @pytest.mark.asyncio
    async def test_list_is_two_queries(
        self, session_maker: SessionMaker, test_redis_client: Redis, login
    ):
        from app.api.schemas.disputes import DisputeListQuery
        from app.api.services.disputes import DisputeService

        merchant: UUID = await _merchant(session_maker)
        for _ in range(3):
            await _dispute(session_maker, merchant)

        service = DisputeService(test_redis_client)
        count: int = await self._count(
            session_maker, lambda m, uow: service.list_disputes(m, DisputeListQuery(), uow)
        )
        # the page with its total; readiness only queries for matched payments (none here)
        assert count == 1

        matched: UUID = await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(await _order_id(session_maker, merchant)),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )
        await _dispute(session_maker, merchant, matched)
        count = await self._count(
            session_maker, lambda m, uow: service.list_disputes(m, DisputeListQuery(), uow)
        )
        # plus one query for the whole page's readiness
        assert count == 2

    @pytest.mark.asyncio
    async def test_detail_is_four_queries(
        self, session_maker: SessionMaker, test_redis_client: Redis, login
    ):
        from app.api.services.disputes import DisputeService

        merchant: UUID = await _merchant(session_maker)
        dispute_id: UUID = await _dispute(session_maker, merchant)

        service = DisputeService(test_redis_client)
        count: int = await self._count(
            session_maker, lambda m, uow: service.get_dispute(m, dispute_id, uow)
        )
        # dispute + payment + customer + order + history in one, then fulfillments and files
        # (readiness adds one more for a matched payment)
        assert count == 3
