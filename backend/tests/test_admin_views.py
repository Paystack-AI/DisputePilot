"""An admin reading one merchant's data through the merchant's own services."""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import ReconciliationStatus
from app.api.models.trust_profiles import TrustProfile
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_fulfillment, add_transaction, merchant_id
from tests.test_admin import admin_headers  # noqa: F401  (fixture)
from tests.test_disputes import _dispute

SessionMaker = async_sessionmaker[AsyncSession]


async def _demo_shop(
    async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
) -> dict:
    """A merchant with an order, its matched payment, a fulfillment, a dispute and a
    reconciliation session, made through the merchant's own api"""
    merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
    order = (
        await async_client.post(
            "/orders",
            json={"amount": 4500000, "order_number": "A-1", "customer_email": "ada@example.com"},
            headers=auth_headers,
        )
    ).json()["data"]
    paid: UUID = await add_transaction(
        session_maker,
        merchant,
        customer_id=UUID(order["customer"]["id"]),
        order_id=UUID(order["id"]),
        reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
    )
    fulfillment: UUID = await add_fulfillment(session_maker, merchant, UUID(order["id"]), paid)
    dispute: UUID = await _dispute(session_maker, merchant, paid)
    session = await async_client.post("/reconciliation/start", json={}, headers=auth_headers)
    assert session.status_code == 201, session.text
    return {
        "merchant": str(merchant),
        "order": order["id"],
        "customer": order["customer"]["id"],
        "paid": str(paid),
        "fulfillment": str(fulfillment),
        "dispute": str(dispute),
    }


class TestAdminMerchantViews:
    @pytest.mark.asyncio
    async def test_everything_the_merchant_sees(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        admin_headers: dict,  # noqa: F811
        session_maker: SessionMaker,
        queued_trust: MagicMock,
    ):
        made: dict = await _demo_shop(async_client, auth_headers, session_maker)
        # only what the admin's views queue counts from here
        queued_trust.reset_mock()
        base: str = f"/admin/merchants/{made['merchant']}"

        async def get(path: str) -> dict:
            res: Response = await async_client.get(base + path, headers=admin_headers)
            assert res.status_code == 200, f"{path}: {res.text}"
            return res.json()

        dashboard: dict = (await get("/dashboard"))["data"]
        assert dashboard["metrics"]["disputes"]["open"] == 1

        transactions: list = (await get("/transactions"))["data"]
        assert [t["id"] for t in transactions] == [made["paid"]]
        reference: str = transactions[0]["reference"]
        assert (await get(f"/transactions/{reference}"))["data"]["order"]["id"] == made["order"]

        assert [o["id"] for o in (await get("/orders"))["data"]] == [made["order"]]
        assert (await get(f"/orders/{made['order']}"))["data"]["id"] == made["order"]

        assert [c["id"] for c in (await get("/customers"))["data"]] == [made["customer"]]
        ledger: list = (await get(f"/customers/{made['customer']}/ledger"))["data"]
        assert {entry["kind"] for entry in ledger} == {"order", "payment", "fulfillment", "dispute"}

        fulfillments: list = (await get("/fulfillments"))["data"]
        assert [f["id"] for f in fulfillments] == [made["fulfillment"]]
        assert (await get(f"/fulfillments/{made['fulfillment']}"))["data"]["id"] == (
            made["fulfillment"]
        )

        reconciliation: dict = (await get("/reconciliation/current"))["data"]
        assert reconciliation["session"]["status"] == "in_progress"
        session_id: str = reconciliation["session"]["id"]
        assert [s["id"] for s in (await get("/reconciliation/sessions"))["data"]] == [session_id]
        assert (await get(f"/reconciliation/sessions/{session_id}"))["data"]["session"]["id"] == (
            session_id
        )
        assert "needs_review" in (await get("/reconciliation/summary"))["data"]

        assert [d["id"] for d in (await get("/disputes"))["data"]] == [made["dispute"]]
        detail: dict = (await get(f"/disputes/{made['dispute']}"))["data"]
        assert detail["evidence"]["header"]["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert (await get("/disputes/stats"))["data"]["open"] == 1

        # the merchant never opened TrustLayer: viewing it creates nothing
        for path in ("/trust/profile", "/trust/signals", "/trust/actions"):
            res: Response = await async_client.get(base + path, headers=admin_headers)
            assert res.status_code == 404, path
        async with session_maker() as session:
            profiles = await session.scalar(
                select(func.count(TrustProfile.id)).where(
                    TrustProfile.merchant_id == UUID(made["merchant"])
                )
            )
        assert profiles == 0
        queued_trust.assert_not_called()
        assert (await get("/trust/history?days=30"))["data"]["days"] == 30

        # once the merchant has opened it, the admin sees the same profile
        await async_client.get("/trust/profile", headers=auth_headers)
        assert (await get("/trust/profile"))["data"]["state"] == "new"
        assert "signals" in (await get("/trust/signals"))["data"]
        assert (await get("/trust/actions"))["data"]["actions"] == []

    @pytest.mark.asyncio
    async def test_admins_only(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])

        # a merchant's token, even for its own id, is not an admin token
        res: Response = await async_client.get(
            f"/admin/merchants/{merchant}/transactions", headers=auth_headers
        )
        assert res.status_code == 401
        res = await async_client.get(f"/admin/merchants/{merchant}/dashboard")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_merchant(
        self,
        async_client: AsyncClient,
        admin_headers: dict,  # noqa: F811
    ):
        res: Response = await async_client.get(
            f"/admin/merchants/{uuid4()}/orders", headers=admin_headers
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_read_only(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        admin_headers: dict,  # noqa: F811
        session_maker: SessionMaker,
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        # no admin route writes merchant data
        for method, path in (
            ("POST", "/orders"),
            ("PUT", "/disputes/x/evidence"),
            ("POST", "/reconciliation/start"),
        ):
            res: Response = await async_client.request(
                method, f"/admin/merchants/{merchant}{path}", headers=admin_headers, json={}
            )
            assert res.status_code in (404, 405), (method, path, res.status_code)
