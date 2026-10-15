from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import ReconciliationStatus, TransactionStatus
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import (
    add_dispute,
    add_fulfillment,
    add_transaction,
    merchant_id,
    sign_in_merchant,
)

SessionMaker = async_sessionmaker[AsyncSession]


async def _create(async_client: AsyncClient, headers: dict, payload: dict) -> Response:
    return await async_client.post("/customers", json=payload, headers=headers)


async def _customer_id(async_client: AsyncClient, headers: dict, payload: dict) -> str:
    res: Response = await _create(async_client, headers, payload)
    assert res.status_code == 201, res.text
    return res.json()["data"]["id"]


class TestCreateCustomer:
    @pytest.mark.asyncio
    async def test_create(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _create(
            async_client,
            auth_headers,
            {"name": "Amina Yusuf", "email": "Amina@Example.com", "phone": "+234 803 123 4567"},
        )
        data: dict = res.json()["data"]

        assert res.status_code == 201
        assert data["name"] == "Amina Yusuf"
        assert data["email"] == "amina@example.com"
        assert data["phone"] == "+2348031234567"
        assert data["is_shared"] is False
        assert data["paystack_customer_code"] is None
        assert data["stats"] == {
            "payment_count": 0,
            "reconciled_count": 0,
            "reconciled_pct": None,
            "fulfilled_count": 0,
            "order_count": 0,
            "dispute_count": 0,
            "dispute_rate": None,
            "first_payment_at": None,
            "last_payment_at": None,
        }

    @pytest.mark.asyncio
    async def test_cash_customer_without_email(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _create(async_client, auth_headers, {"name": "Walk-in Tunde"})

        assert res.status_code == 201
        assert res.json()["data"]["email"] is None

    @pytest.mark.asyncio
    async def test_merchant_email_is_shared(self, async_client: AsyncClient, auth_headers: dict):
        # merchants often enter their own email at checkout for walk-in buyers
        res: Response = await _create(
            async_client, auth_headers, {"email": SIGN_UP_PAYLOAD["email"].upper()}
        )

        assert res.status_code == 201
        assert res.json()["data"]["is_shared"] is True

    @pytest.mark.asyncio
    async def test_existing_email(self, async_client: AsyncClient, auth_headers: dict):
        first_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )

        res: Response = await _create(async_client, auth_headers, {"email": "AMINA@example.com"})

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "CUSTOMER_EXISTS"
        assert res.json()["error"]["details"] == {"customer_id": first_id}

    @pytest.mark.asyncio
    async def test_same_email_other_merchant(self, async_client: AsyncClient, auth_headers: dict):
        await _customer_id(async_client, auth_headers, {"email": "amina@example.com"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await _create(async_client, other_headers, {"email": "amina@example.com"})

        assert res.status_code == 201

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"phone": "+2348031234567"},  # no name or email
            {"name": ""},
            {"email": "not-an-email"},
            {"name": "Amina", "phone": "08031234567"},  # no country code
            {"name": "Amina", "is_shared": True},  # set automatically on create
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
        res: Response = await _create(async_client, {}, {"name": "Amina"})

        assert res.status_code == 401


class TestGetCustomer:
    @pytest.mark.asyncio
    async def test_stats(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        customer_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )
        customer = UUID(customer_id)
        order = await async_client.post(
            "/orders", json={"amount": 4500000, "customer_id": customer_id}, headers=auth_headers
        )
        order_id = UUID(order.json()["data"]["id"])

        first_paid = datetime(2026, 9, 1, 10, tzinfo=UTC)
        last_paid = datetime(2026, 9, 20, 10, tzinfo=UTC)
        matched = await add_transaction(
            session_maker,
            merchant,
            customer_id=customer,
            order_id=order_id,
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
            paid_at=first_paid,
        )
        await add_fulfillment(session_maker, merchant, order_id, matched)
        disputed = await add_transaction(session_maker, merchant, customer, paid_at=last_paid)
        await add_dispute(session_maker, merchant, disputed)
        await add_transaction(session_maker, merchant, customer, paid_at=last_paid)
        await add_transaction(session_maker, merchant, customer, paid_at=last_paid)
        # failed payments are not counted
        await add_transaction(
            session_maker,
            merchant,
            customer,
            status=TransactionStatus.FAILED,
            paid_at=last_paid + timedelta(days=1),
        )

        res: Response = await async_client.get(f"/customers/{customer_id}", headers=auth_headers)
        stats: dict = res.json()["data"]["stats"]

        assert res.status_code == 200
        assert stats["payment_count"] == 4
        assert stats["reconciled_count"] == 1
        assert stats["reconciled_pct"] == 25
        assert stats["fulfilled_count"] == 1
        assert stats["order_count"] == 1
        assert stats["dispute_count"] == 1
        assert stats["dispute_rate"] == 25.0
        assert stats["first_payment_at"] == "2026-09-01T10:00:00Z"
        assert stats["last_payment_at"] == "2026-09-20T10:00:00Z"
        # money totals are out of scope
        assert "total_spent" not in res.json()["data"]

    @pytest.mark.asyncio
    async def test_other_merchants_customer(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Amina"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get(f"/customers/{customer_id}", headers=other_headers)

        # 404, not 403, so existence is not revealed
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_unknown_customer(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get(
            "/customers/0192f0c1-0000-7000-8000-000000000000", headers=auth_headers
        )

        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Customer not found."


class TestUpdateCustomer:
    @pytest.mark.asyncio
    async def test_update(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )

        res: Response = await async_client.patch(
            f"/customers/{customer_id}",
            json={"name": "Amina Yusuf", "phone": "+2348031234567", "is_shared": True},
            headers=auth_headers,
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["name"] == "Amina Yusuf"
        assert data["phone"] == "+2348031234567"
        assert data["is_shared"] is True
        assert data["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_email_of_cash_customer(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Tunde"})

        res: Response = await async_client.patch(
            f"/customers/{customer_id}", json={"email": "Tunde@Mail.com"}, headers=auth_headers
        )

        assert res.status_code == 200
        assert res.json()["data"]["email"] == "tunde@mail.com"

    @pytest.mark.asyncio
    async def test_email_locked_after_payments(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        customer_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )
        await add_transaction(session_maker, merchant, UUID(customer_id))

        res: Response = await async_client.patch(
            f"/customers/{customer_id}", json={"email": "new@example.com"}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "CUSTOMER_EMAIL_LOCKED"

    @pytest.mark.asyncio
    async def test_email_taken(self, async_client: AsyncClient, auth_headers: dict):
        taken_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Tunde"})

        res: Response = await async_client.patch(
            f"/customers/{customer_id}", json={"email": "amina@example.com"}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"customer_id": taken_id}

    @pytest.mark.asyncio
    async def test_name_or_email_stays_required(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Tunde"})

        res: Response = await async_client.patch(
            f"/customers/{customer_id}", json={"name": None}, headers=auth_headers
        )

        assert res.status_code == 422
        assert res.json()["error"]["details"] == {"name": "name or email is required"}

    @pytest.mark.asyncio
    async def test_other_merchants_customer(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Amina"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.patch(
            f"/customers/{customer_id}", json={"name": "Taken over"}, headers=other_headers
        )

        assert res.status_code == 404


class TestListCustomers:
    @pytest.mark.asyncio
    async def test_list_with_counts(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        amina = UUID(await _customer_id(async_client, auth_headers, {"email": "amina@example.com"}))
        tunde = UUID(await _customer_id(async_client, auth_headers, {"email": "tunde@mail.com"}))
        await _customer_id(async_client, auth_headers, {"name": "Cash only"})

        paid_at = datetime(2026, 9, 20, 10, tzinfo=UTC)
        await add_transaction(
            session_maker,
            merchant,
            amina,
            reconciliation_status=ReconciliationStatus.MANUALLY_MATCHED,
            paid_at=paid_at,
        )
        await add_transaction(session_maker, merchant, amina, paid_at=paid_at - timedelta(days=2))
        disputed = await add_transaction(session_maker, merchant, tunde)
        await add_dispute(session_maker, merchant, disputed)

        res: Response = await async_client.get(
            "/customers", params={"sort": "-payment_count"}, headers=auth_headers
        )
        body: dict = res.json()

        assert res.status_code == 200
        assert body["meta"] == {"page": 1, "limit": 20, "total": 3, "total_pages": 1}
        assert [row["email"] for row in body["data"]] == [
            "amina@example.com",
            "tunde@mail.com",
            None,
        ]
        assert body["data"][0]["payment_count"] == 2
        assert body["data"][0]["reconciled_pct"] == 50
        assert body["data"][0]["last_payment_at"] == "2026-09-20T10:00:00Z"
        assert body["data"][1]["dispute_count"] == 1
        assert body["data"][2]["reconciled_pct"] is None

    @pytest.mark.asyncio
    async def test_search_and_shared_filter(self, async_client: AsyncClient, auth_headers: dict):
        await _customer_id(async_client, auth_headers, {"name": "Amina Yusuf"})
        await _customer_id(async_client, auth_headers, {"email": "amina_y@example.com"})
        await _customer_id(async_client, auth_headers, {"email": SIGN_UP_PAYLOAD["email"]})

        res: Response = await async_client.get(
            "/customers", params={"search": "AMINA"}, headers=auth_headers
        )
        assert res.json()["meta"]["total"] == 2

        # % and _ are matched literally
        res = await async_client.get("/customers", params={"search": "a_y"}, headers=auth_headers)
        assert [row["email"] for row in res.json()["data"]] == ["amina_y@example.com"]

        res = await async_client.get(
            "/customers", params={"is_shared": "true"}, headers=auth_headers
        )
        assert [row["email"] for row in res.json()["data"]] == [SIGN_UP_PAYLOAD["email"]]

    @pytest.mark.asyncio
    async def test_pagination(self, async_client: AsyncClient, auth_headers: dict):
        for number in range(5):
            await _customer_id(async_client, auth_headers, {"name": f"Customer {number}"})

        first: Response = await async_client.get(
            "/customers", params={"limit": 2, "sort": "name"}, headers=auth_headers
        )
        last: Response = await async_client.get(
            "/customers", params={"limit": 2, "page": 3, "sort": "name"}, headers=auth_headers
        )

        assert first.json()["meta"] == {"page": 1, "limit": 2, "total": 5, "total_pages": 3}
        assert [row["name"] for row in first.json()["data"]] == ["Customer 0", "Customer 1"]
        assert [row["name"] for row in last.json()["data"]] == ["Customer 4"]

        # past the end there is no row to carry the window count; the total is still right
        past: Response = await async_client.get(
            "/customers", params={"limit": 2, "page": 9}, headers=auth_headers
        )
        assert past.json()["data"] == []
        assert past.json()["meta"] == {"page": 9, "limit": 2, "total": 5, "total_pages": 3}

    @pytest.mark.asyncio
    async def test_only_own_customers(self, async_client: AsyncClient, auth_headers: dict):
        await _customer_id(async_client, auth_headers, {"name": "Amina"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get("/customers", headers=other_headers)

        assert res.json()["data"] == []
        assert res.json()["meta"]["total"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params", [{"limit": 101}, {"limit": 0}, {"page": 0}, {"sort": "total_spent"}]
    )
    async def test_invalid_query(self, async_client: AsyncClient, auth_headers: dict, params: dict):
        res: Response = await async_client.get("/customers", params=params, headers=auth_headers)

        assert res.status_code == 422


class TestCustomerSubResources:
    @pytest.mark.asyncio
    async def test_transactions(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        customer_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )
        other_id: str = await _customer_id(async_client, auth_headers, {"email": "tunde@mail.com"})
        older = await add_transaction(
            session_maker, merchant, UUID(customer_id), paid_at=datetime(2026, 9, 1, tzinfo=UTC)
        )
        newer = await add_transaction(
            session_maker, merchant, UUID(customer_id), paid_at=datetime(2026, 9, 2, tzinfo=UTC)
        )
        await add_transaction(session_maker, merchant, UUID(other_id))

        res: Response = await async_client.get(
            f"/customers/{customer_id}/transactions", headers=auth_headers
        )
        body: dict = res.json()

        assert res.status_code == 200
        assert [row["id"] for row in body["data"]] == [str(newer), str(older)]
        assert body["meta"]["total"] == 2
        # paystack numeric ids are strings
        assert isinstance(body["data"][0]["paystack_transaction_id"], str)

    @pytest.mark.asyncio
    async def test_orders(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(
            async_client, auth_headers, {"email": "amina@example.com"}
        )
        await async_client.post(
            "/orders", json={"amount": 100000, "customer_id": customer_id}, headers=auth_headers
        )
        await async_client.post(
            "/orders",
            json={"amount": 200000, "customer_email": "amina@example.com"},
            headers=auth_headers,
        )
        await async_client.post("/orders", json={"amount": 300000}, headers=auth_headers)

        res: Response = await async_client.get(
            f"/customers/{customer_id}/orders", headers=auth_headers
        )

        assert res.status_code == 200
        assert [row["amount"] for row in res.json()["data"]] == [200000, 100000]

    @pytest.mark.asyncio
    async def test_other_merchants_customer(self, async_client: AsyncClient, auth_headers: dict):
        customer_id: str = await _customer_id(async_client, auth_headers, {"name": "Amina"})
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        for path in ("transactions", "orders"):
            res: Response = await async_client.get(
                f"/customers/{customer_id}/{path}", headers=other_headers
            )
            assert res.status_code == 404
