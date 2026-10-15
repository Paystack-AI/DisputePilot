from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import OrderStatus, ReconciliationStatus
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import (
    add_fulfillment,
    add_transaction,
    merchant_id,
    set_order,
    sign_in_merchant,
)

SessionMaker = async_sessionmaker[AsyncSession]


async def _create(async_client: AsyncClient, headers: dict, payload: dict) -> Response:
    return await async_client.post("/orders", json=payload, headers=headers)


async def _order(async_client: AsyncClient, headers: dict, payload: dict) -> dict:
    res: Response = await _create(async_client, headers, payload)
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def _link(session_maker: SessionMaker, order: dict) -> UUID:
    """A payment matched to the order by reconciliation"""
    merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
    return await add_transaction(
        session_maker,
        merchant,
        order_id=UUID(order["id"]),
        amount=order["amount"],
        reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
    )


class TestCreateOrder:
    @pytest.mark.asyncio
    async def test_minimal(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _create(async_client, auth_headers, {"amount": 4500000})
        data: dict = res.json()["data"]

        assert res.status_code == 201
        assert data["order_number"] is None
        assert data["customer"] is None
        assert data["amount"] == 4500000
        assert data["currency"] == "NGN"
        assert data["status"] == "pending"
        assert data["source"] == "other"
        assert data["is_linked"] is False

    @pytest.mark.asyncio
    async def test_default_currency_from_settings(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        await async_client.patch(
            "/settings", json={"default_currency": "GHS"}, headers=auth_headers
        )

        data: dict = await _order(async_client, auth_headers, {"amount": 5000})

        assert data["currency"] == "GHS"

    @pytest.mark.asyncio
    async def test_full(self, async_client: AsyncClient, auth_headers: dict):
        data: dict = await _order(
            async_client,
            auth_headers,
            {
                "order_number": " ORD-1032 ",
                "description": "Two-seater sofa",
                "amount": 4500000,
                "currency": "USD",
                "source": "whatsapp",
            },
        )

        assert data["order_number"] == "ORD-1032"
        assert data["description"] == "Two-seater sofa"
        assert data["currency"] == "USD"
        assert data["source"] == "whatsapp"

    @pytest.mark.asyncio
    async def test_customer_email_creates_then_reuses_customer(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        first: dict = await _order(
            async_client,
            auth_headers,
            {"amount": 1000, "customer_email": "Tunde@Mail.com", "customer_name": "Tunde Bello"},
        )
        second: dict = await _order(
            async_client, auth_headers, {"amount": 2000, "customer_email": "tunde@mail.com"}
        )

        assert first["customer"]["email"] == "tunde@mail.com"
        assert first["customer"]["name"] == "Tunde Bello"
        assert second["customer"]["id"] == first["customer"]["id"]

        res: Response = await async_client.get("/customers", headers=auth_headers)
        assert res.json()["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_merchant_email_customer_is_shared(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        data: dict = await _order(
            async_client, auth_headers, {"amount": 1000, "customer_email": SIGN_UP_PAYLOAD["email"]}
        )

        assert data["customer"]["is_shared"] is True

    @pytest.mark.asyncio
    async def test_customer_id(self, async_client: AsyncClient, auth_headers: dict):
        customer = await async_client.post(
            "/customers", json={"name": "Amina"}, headers=auth_headers
        )
        customer_id: str = customer.json()["data"]["id"]

        data: dict = await _order(
            async_client, auth_headers, {"amount": 1000, "customer_id": customer_id}
        )

        assert data["customer"] == {
            "id": customer_id,
            "name": "Amina",
            "email": None,
            "is_shared": False,
        }

    @pytest.mark.asyncio
    async def test_other_merchants_customer(self, async_client: AsyncClient, auth_headers: dict):
        customer = await async_client.post(
            "/customers", json={"name": "Amina"}, headers=auth_headers
        )
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await _create(
            async_client,
            other_headers,
            {"amount": 1000, "customer_id": customer.json()["data"]["id"]},
        )

        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Customer not found."

    @pytest.mark.asyncio
    async def test_order_number_taken(self, async_client: AsyncClient, auth_headers: dict):
        await _order(async_client, auth_headers, {"amount": 1000, "order_number": "ORD-1032"})

        # compared ignoring case, like tier 1 matching
        res: Response = await _create(
            async_client, auth_headers, {"amount": 1000, "order_number": "ord-1032"}
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_NUMBER_EXISTS"

    @pytest.mark.asyncio
    async def test_order_number_per_merchant(self, async_client: AsyncClient, auth_headers: dict):
        await _order(async_client, auth_headers, {"amount": 1000, "order_number": "ORD-1032"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await _create(
            async_client, other_headers, {"amount": 1000, "order_number": "ORD-1032"}
        )

        assert res.status_code == 201

    @pytest.mark.asyncio
    async def test_many_orders_without_number(self, async_client: AsyncClient, auth_headers: dict):
        await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await _create(async_client, auth_headers, {"amount": 1000})

        assert res.status_code == 201

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"amount": 0},
            {"amount": -100},
            {"amount": 10.5},
            {"amount": 1000, "currency": "EUR"},
            {"amount": 1000, "source": "tiktok"},
            {"amount": 1000, "status": "paid"},
            {"amount": 1000, "order_number": ""},
            {"amount": 1000, "order_number": "x" * 51},
            {"amount": 1000, "customer_email": "not-an-email"},
            {
                "amount": 1000,
                "customer_id": "0192f0c1-0000-7000-8000-000000000000",
                "customer_email": "amina@example.com",
            },
            {"amount": 1000, "customer_name": "Amina"},
        ],
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, payload: dict
    ):
        res: Response = await _create(async_client, auth_headers, payload)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await _create(async_client, {}, {"amount": 1000})

        assert res.status_code == 401


class TestGetOrder:
    @pytest.mark.asyncio
    async def test_detail(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        order: dict = await _order(
            async_client,
            auth_headers,
            {"amount": 4500000, "order_number": "ORD-1", "customer_email": "amina@example.com"},
        )
        transaction_id = await _link(session_maker, order)
        fulfillment_id = await add_fulfillment(
            session_maker, merchant, UUID(order["id"]), transaction_id
        )

        res: Response = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["is_linked"] is True
        assert data["customer"]["email"] == "amina@example.com"
        assert [t["id"] for t in data["transactions"]] == [str(transaction_id)]
        assert data["transactions"][0]["reconciliation_status"] == "auto_matched"
        assert [f["id"] for f in data["fulfillments"]] == [str(fulfillment_id)]

    @pytest.mark.asyncio
    async def test_without_links(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)

        assert res.json()["data"]["transactions"] == []
        assert res.json()["data"]["fulfillments"] == []
        assert res.json()["data"]["is_linked"] is False

    @pytest.mark.asyncio
    async def test_other_merchants_order(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get(f"/orders/{order['id']}", headers=other_headers)

        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Order not found."


class TestListOrders:
    @pytest.mark.asyncio
    async def test_filters(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        amina: dict = await _order(
            async_client,
            auth_headers,
            {"amount": 3000, "order_number": "ORD-3", "customer_email": "amina@example.com"},
        )
        cancelled: dict = await _order(
            async_client, auth_headers, {"amount": 1000, "description": "Blue sofa"}
        )
        paid: dict = await _order(async_client, auth_headers, {"amount": 2000})
        await set_order(session_maker, cancelled["id"], status=OrderStatus.CANCELLED)
        await set_order(session_maker, paid["id"], status=OrderStatus.PAID)

        async def ids(params: dict) -> list[str]:
            res = await async_client.get("/orders", params=params, headers=auth_headers)
            assert res.status_code == 200, res.text
            return [row["id"] for row in res.json()["data"]]

        assert await ids({"status": "pending,paid", "sort": "amount"}) == [paid["id"], amina["id"]]
        assert await ids({"customer_id": amina["customer"]["id"]}) == [amina["id"]]
        assert await ids({"search": "sofa"}) == [cancelled["id"]]
        assert await ids({"search": "AMINA@"}) == [amina["id"]]
        assert await ids({"search": "ord-3"}) == [amina["id"]]
        assert await ids({"sort": "-amount"}) == [amina["id"], paid["id"], cancelled["id"]]

    @pytest.mark.asyncio
    async def test_dates_in_merchant_timezone(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await async_client.patch(
            "/settings", json={"timezone": "Africa/Lagos"}, headers=auth_headers
        )
        late: dict = await _order(async_client, auth_headers, {"amount": 1000})
        early: dict = await _order(async_client, auth_headers, {"amount": 2000})
        # 00:30 on 2 October in Lagos (UTC+1), but still 1 October in UTC
        await set_order(
            session_maker, late["id"], created_at=datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
        )
        # 23:30 on 1 October in Lagos
        await set_order(
            session_maker, early["id"], created_at=datetime(2026, 10, 1, 22, 30, tzinfo=UTC)
        )

        res: Response = await async_client.get(
            "/orders",
            params={"date_from": "2026-10-02", "date_to": "2026-10-02"},
            headers=auth_headers,
        )
        assert [row["id"] for row in res.json()["data"]] == [late["id"]]

        res = await async_client.get(
            "/orders", params={"date_to": "2026-10-01"}, headers=auth_headers
        )
        assert [row["id"] for row in res.json()["data"]] == [early["id"]]

    @pytest.mark.asyncio
    async def test_link_state_and_pagination(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        orders: list[dict] = [
            await _order(async_client, auth_headers, {"amount": 1000 * (n + 1)}) for n in range(3)
        ]
        await _link(session_maker, orders[0])

        res: Response = await async_client.get(
            "/orders", params={"limit": 2, "page": 2}, headers=auth_headers
        )
        body: dict = res.json()

        assert body["meta"] == {"page": 2, "limit": 2, "total": 3, "total_pages": 2}
        # newest first, so the oldest (linked) order is on the last page
        assert [row["id"] for row in body["data"]] == [orders[0]["id"]]
        assert body["data"][0]["is_linked"] is True

    @pytest.mark.asyncio
    async def test_only_own_orders(self, async_client: AsyncClient, auth_headers: dict):
        await _order(async_client, auth_headers, {"amount": 1000})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get("/orders", headers=other_headers)

        assert res.json()["meta"]["total"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"status": "partially_paid"},
            {"date_from": "2026-10-02", "date_to": "2026-10-01"},
            {"date_from": "02-10-2026"},
            {"sort": "customer"},
            {"limit": 101},
        ],
    )
    async def test_invalid_query(self, async_client: AsyncClient, auth_headers: dict, params: dict):
        res: Response = await async_client.get("/orders", params=params, headers=auth_headers)

        assert res.status_code == 422


class TestUpdateOrder:
    @pytest.mark.asyncio
    async def test_update(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await async_client.patch(
            f"/orders/{order['id']}",
            json={
                "order_number": "ORD-7",
                "description": "Gift wrap",
                "amount": 1500,
                "currency": "KES",
                "source": "instagram",
            },
            headers=auth_headers,
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["order_number"] == "ORD-7"
        assert data["amount"] == 1500
        assert data["currency"] == "KES"
        assert data["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_clear_number_and_customer(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(
            async_client,
            auth_headers,
            {"amount": 1000, "order_number": "ORD-7", "customer_email": "amina@example.com"},
        )

        res: Response = await async_client.patch(
            f"/orders/{order['id']}",
            json={"order_number": None, "customer_id": None},
            headers=auth_headers,
        )

        assert res.json()["data"]["order_number"] is None
        assert res.json()["data"]["customer"] is None

    @pytest.mark.asyncio
    async def test_linked_order_locks_matched_fields(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(
            async_client, auth_headers, {"amount": 1000, "order_number": "ORD-7"}
        )
        await _link(session_maker, order)

        res: Response = await async_client.patch(
            f"/orders/{order['id']}",
            json={"amount": 2000, "order_number": "ORD-8"},
            headers=auth_headers,
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_LINKED"
        assert res.json()["error"]["details"] == {"fields": "order_number, amount"}

    @pytest.mark.asyncio
    async def test_linked_order_other_fields(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        await _link(session_maker, order)

        # resending unchanged locked values is harmless
        res: Response = await async_client.patch(
            f"/orders/{order['id']}",
            json={"amount": 1000, "description": "Delivered to the front desk"},
            headers=auth_headers,
        )

        assert res.status_code == 200
        assert res.json()["data"]["description"] == "Delivered to the front desk"
        assert res.json()["data"]["is_linked"] is True

    @pytest.mark.asyncio
    async def test_order_number_taken(self, async_client: AsyncClient, auth_headers: dict):
        await _order(async_client, auth_headers, {"amount": 1000, "order_number": "ORD-1"})
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await async_client.patch(
            f"/orders/{order['id']}", json={"order_number": "Ord-1"}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_NUMBER_EXISTS"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "current, new, allowed",
        [
            (OrderStatus.PENDING, OrderStatus.CANCELLED, True),
            (OrderStatus.PAID, OrderStatus.FULFILLED, True),
            # paid is only set by reconciliation
            (OrderStatus.PENDING, OrderStatus.PAID, False),
            (OrderStatus.PENDING, OrderStatus.FULFILLED, False),
            (OrderStatus.CANCELLED, OrderStatus.PENDING, False),
            (OrderStatus.FULFILLED, OrderStatus.PAID, False),
        ],
    )
    async def test_status_transitions(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        current: OrderStatus,
        new: OrderStatus,
        allowed: bool,
    ):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        await set_order(session_maker, order["id"], status=current)

        res: Response = await async_client.patch(
            f"/orders/{order['id']}", json={"status": new}, headers=auth_headers
        )

        if allowed:
            assert res.status_code == 200
            assert res.json()["data"]["status"] == new
        else:
            assert res.status_code == 409
            assert res.json()["error"]["code"] == "ORDER_STATUS_TRANSITION"
            assert res.json()["error"]["details"] == {"current_status": current}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [{"amount": None}, {"amount": 0}, {"status": None}, {"currency": None}, {"unknown": 1}],
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, payload: dict
    ):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await async_client.patch(
            f"/orders/{order['id']}", json=payload, headers=auth_headers
        )

        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_other_merchants_order(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.patch(
            f"/orders/{order['id']}", json={"description": "x"}, headers=other_headers
        )

        assert res.status_code == 404


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})

        res: Response = await async_client.delete(f"/orders/{order['id']}", headers=auth_headers)
        again: Response = await async_client.delete(f"/orders/{order['id']}", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["data"]["status"] == "cancelled"
        # soft delete, so the order is still there and cancelling again is a no-op
        assert again.status_code == 200
        res = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)
        assert res.json()["data"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_linked_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        await _link(session_maker, order)

        res: Response = await async_client.delete(f"/orders/{order['id']}", headers=auth_headers)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_LINKED"

    @pytest.mark.asyncio
    async def test_fulfilled_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        await set_order(session_maker, order["id"], status=OrderStatus.FULFILLED)

        res: Response = await async_client.delete(f"/orders/{order['id']}", headers=auth_headers)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_STATUS_TRANSITION"

    @pytest.mark.asyncio
    async def test_other_merchants_order(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers, {"amount": 1000})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.delete(f"/orders/{order['id']}", headers=other_headers)

        assert res.status_code == 404
