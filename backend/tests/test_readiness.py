from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.customers import Customer
from app.api.models.enums import ReconciliationStatus
from app.api.models.files import StoredFile
from app.api.models.transactions import Transaction
from app.api.services.readiness import ReadinessFacts, label_for, score_readiness
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_fulfillment, add_transaction, merchant_id

SessionMaker = async_sessionmaker[AsyncSession]

NONE = ReadinessFacts(False, False, False, False, False, False)
ALL = ReadinessFacts(True, True, True, True, True, True)


class TestScore:
    def test_everything_is_100(self):
        detail = score_readiness(ALL)
        assert (detail.score, detail.label) == (100, "well_defended")
        assert all(c.status == "available" and c.suggestion is None for c in detail.components)

    def test_payment_alone_is_20(self):
        detail = score_readiness(NONE)
        assert (detail.score, detail.label) == (20, "vulnerable")
        missing = [c for c in detail.components if c.status == "missing"]
        assert len(missing) == 6
        assert all(c.points == 0 and c.max_points > 0 and c.suggestion for c in missing)

    def test_matched_with_fulfillment(self):
        facts = ReadinessFacts(True, True, True, False, True, False)
        # 20 + 15 + 10 + 20 + 10
        assert score_readiness(facts).score == 75

    def test_bands(self):
        assert label_for(70) == "well_defended"
        assert label_for(69) == "moderate"
        assert label_for(40) == "moderate"
        assert label_for(39) == "vulnerable"


async def _merchant(session_maker: SessionMaker) -> UUID:
    return await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])


async def _reference(session_maker: SessionMaker, transaction_id: UUID) -> str:
    async with session_maker() as session:
        return await session.scalar(
            select(Transaction.paystack_reference).where(Transaction.id == transaction_id)
        )


async def _order(async_client: AsyncClient, headers: dict, **fields) -> dict:
    res: Response = await async_client.post(
        "/orders", json={"amount": 4500000, **fields}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


class TestEndpoints:
    @pytest.mark.asyncio
    async def test_unmatched_has_no_score(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await add_transaction(session_maker, await _merchant(session_maker))

        res: Response = await async_client.get("/transactions", headers=auth_headers)

        assert res.json()["data"][0]["readiness"] is None

    @pytest.mark.asyncio
    async def test_matched_by_hand_is_scored(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        order = await _order(async_client, auth_headers)
        reference: str = await _reference(
            session_maker, await add_transaction(session_maker, merchant)
        )

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        assert res.status_code == 200, res.text
        # payment and order, no customer, fulfillment or history
        assert res.json()["data"]["readiness"] == {"score": 35, "label": "vulnerable"}

    @pytest.mark.asyncio
    async def test_full_evidence(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        order = await _order(async_client, auth_headers, customer_email="ada@example.com")
        customer_id = UUID(order["customer"]["id"])
        now: datetime = datetime.now(UTC)

        # three earlier payments from the same customer
        for days in (30, 20, 10):
            await add_transaction(
                session_maker, merchant, customer_id=customer_id, paid_at=now - timedelta(days=days)
            )
        transaction_id: UUID = await add_transaction(
            session_maker,
            merchant,
            customer_id=customer_id,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
            paid_at=now,
        )
        fulfillment_id: UUID = await add_fulfillment(session_maker, merchant, UUID(order["id"]))
        async with session_maker() as session:
            session.add(
                StoredFile(
                    merchant_id=merchant,
                    fulfillment_id=fulfillment_id,
                    object_name=f"{merchant}/{uuid4()}.jpg",
                    file_name="door.jpg",
                    content_type="image/jpeg",
                    size=1000,
                    width=10,
                    height=10,
                )
            )
            await session.commit()

        reference: str = await _reference(session_maker, transaction_id)
        res: Response = await async_client.get(f"/transactions/{reference}", headers=auth_headers)

        readiness: dict = res.json()["data"]["readiness"]
        assert (readiness["score"], readiness["label"]) == (100, "well_defended")
        assert {c["key"] for c in readiness["components"]} == {
            "transaction_record",
            "linked_order",
            "customer_record",
            "fulfillment",
            "delivery_photo",
            "tracking_or_signature",
            "repeat_customer",
        }

        # a shared email does not count as a repeat customer
        async with session_maker() as session:
            customer = await session.get(Customer, customer_id)
            customer.is_shared = True
            await session.commit()
        res = await async_client.get("/transactions", headers=auth_headers)
        scored = [t for t in res.json()["data"] if t["readiness"]]
        assert [t["readiness"]["score"] for t in scored] == [90]

    @pytest.mark.asyncio
    async def test_reconciliation_matched_items_are_scored(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _order(async_client, auth_headers, order_number="A-1")
        await add_transaction(session_maker, await _merchant(session_maker), reference="A-1")

        res: Response = await async_client.post(
            "/reconciliation/start", json={}, headers=auth_headers
        )

        matched: dict = res.json()["data"]["matched"][0]
        assert matched["transaction"]["readiness"] == {"score": 35, "label": "vulnerable"}
