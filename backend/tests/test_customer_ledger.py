from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import DisputeStatus, ReconciliationStatus
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_fulfillment, add_transaction, merchant_id, sign_in_merchant
from tests.test_disputes import _dispute

SessionMaker = async_sessionmaker[AsyncSession]


async def _customer_with_history(
    async_client: AsyncClient, headers: dict, session_maker: SessionMaker
) -> tuple[str, dict]:
    """A customer with an order, its payment (disputed) and a fulfillment, plus another
    payment; returns the customer id and the ids made"""
    merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
    order = (
        await async_client.post(
            "/orders",
            json={"amount": 4500000, "order_number": "A-1", "customer_email": "ada@example.com"},
            headers=headers,
        )
    ).json()["data"]
    customer_id: str = order["customer"]["id"]
    now: datetime = datetime.now(UTC)

    paid: UUID = await add_transaction(
        session_maker,
        merchant,
        customer_id=UUID(customer_id),
        order_id=UUID(order["id"]),
        reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        paid_at=now - timedelta(days=3),
    )
    fulfillment: UUID = await add_fulfillment(session_maker, merchant, UUID(order["id"]), paid)
    dispute: UUID = await _dispute(session_maker, merchant, paid)
    other: UUID = await add_transaction(
        session_maker, merchant, customer_id=UUID(customer_id), paid_at=now - timedelta(days=1)
    )
    # someone else's payment and dispute: never in this customer's ledger
    stranger: UUID = await add_transaction(session_maker, merchant)
    await _dispute(session_maker, merchant, stranger)

    return customer_id, {
        "order": order["id"],
        "paid": str(paid),
        "other": str(other),
        "fulfillment": str(fulfillment),
        "dispute": str(dispute),
    }


class TestCustomerDisputes:
    @pytest.mark.asyncio
    async def test_only_this_customers_disputes(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        customer_id, made = await _customer_with_history(async_client, auth_headers, session_maker)

        res: Response = await async_client.get(
            f"/customers/{customer_id}/disputes", headers=auth_headers
        )

        assert res.status_code == 200, res.text
        body: dict = res.json()
        assert [d["id"] for d in body["data"]] == [made["dispute"]]
        assert body["meta"]["total"] == 1
        assert body["data"][0]["status"] == DisputeStatus.PENDING.value

        # the same filter on the dispute list
        res = await async_client.get(f"/disputes?customer_id={customer_id}", headers=auth_headers)
        assert [d["id"] for d in res.json()["data"]] == [made["dispute"]]

    @pytest.mark.asyncio
    async def test_unknown_customer(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get(
            f"/customers/{uuid4()}/disputes", headers=auth_headers
        )
        assert res.status_code == 404


class TestCustomerLedger:
    @pytest.mark.asyncio
    async def test_one_timeline_newest_first(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        customer_id, made = await _customer_with_history(async_client, auth_headers, session_maker)

        res: Response = await async_client.get(
            f"/customers/{customer_id}/ledger", headers=auth_headers
        )

        assert res.status_code == 200, res.text
        body: dict = res.json()
        entries: list[dict] = body["data"]
        assert body["meta"]["total"] == 5
        assert {(e["kind"], e["id"]) for e in entries} == {
            ("order", made["order"]),
            ("payment", made["paid"]),
            ("payment", made["other"]),
            ("fulfillment", made["fulfillment"]),
            ("dispute", made["dispute"]),
        }
        times: list[str] = [e["occurred_at"] for e in entries]
        assert times == sorted(times, reverse=True)

        payment = next(e for e in entries if e["id"] == made["paid"])
        assert payment["order_id"] == made["order"]
        assert payment["status"] == "success"
        fulfillment = next(e for e in entries if e["kind"] == "fulfillment")
        assert (fulfillment["reference"], fulfillment["amount"]) == ("GIG-0012", None)
        dispute = next(e for e in entries if e["kind"] == "dispute")
        assert dispute["transaction_id"] == made["paid"]

    @pytest.mark.asyncio
    async def test_pages(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        customer_id, _ = await _customer_with_history(async_client, auth_headers, session_maker)

        first: dict = (
            await async_client.get(f"/customers/{customer_id}/ledger?limit=2", headers=auth_headers)
        ).json()
        last: dict = (
            await async_client.get(
                f"/customers/{customer_id}/ledger?limit=2&page=3", headers=auth_headers
            )
        ).json()

        assert len(first["data"]) == 2 and first["meta"]["total_pages"] == 3
        assert len(last["data"]) == 1

    @pytest.mark.asyncio
    async def test_other_merchants_customer_is_missing(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        customer_id, _ = await _customer_with_history(async_client, auth_headers, session_maker)
        other: dict = await sign_in_merchant(async_client, "other@shop.example", "Other Shop")

        res: Response = await async_client.get(f"/customers/{customer_id}/ledger", headers=other)

        assert res.status_code == 404
