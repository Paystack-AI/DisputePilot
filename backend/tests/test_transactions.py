from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import InitialSyncStatus, ReconciliationStatus, TransactionStatus
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.transactions import Transaction
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import (
    add_dispute,
    add_fulfillment,
    add_transaction,
    merchant_id,
    set_order,
    sign_in_merchant,
)
from tests.test_paystack import TEST_SECRET_KEY

SessionMaker = async_sessionmaker[AsyncSession]


async def _reference(session_maker: SessionMaker, transaction_id: UUID) -> str:
    async with session_maker() as session:
        return await session.scalar(
            select(Transaction.paystack_reference).where(Transaction.id == transaction_id)
        )


async def _payment(session_maker: SessionMaker, **fields) -> str:
    """A synced payment for the signed in merchant; returns its reference"""
    merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
    return await _reference(session_maker, await add_transaction(session_maker, merchant, **fields))


async def _order(async_client: AsyncClient, headers: dict, **fields) -> dict:
    res: Response = await async_client.post(
        "/orders", json={"amount": 4500000, **fields}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


class TestListTransactions:
    @pytest.mark.asyncio
    async def test_list(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker, customer_email="ada@example.com")

        res: Response = await async_client.get("/transactions", headers=auth_headers)
        data: list[dict] = res.json()["data"]

        assert res.status_code == 200
        assert len(data) == 1
        assert data[0]["reference"] == reference
        assert data[0]["status"] == "success"
        assert data[0]["reconciliation_status"] == "unmatched"
        assert data[0]["order"] is None
        assert data[0]["flag_reason"] is None
        assert res.json()["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_filters(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _payment(session_maker)
        failed: str = await _payment(session_maker, status=TransactionStatus.FAILED)
        flagged: str = await _payment(
            session_maker, reconciliation_status=ReconciliationStatus.FLAGGED
        )

        res: Response = await async_client.get(
            "/transactions", params={"status": "failed"}, headers=auth_headers
        )
        assert [t["reference"] for t in res.json()["data"]] == [failed]

        res = await async_client.get(
            "/transactions",
            params={"reconciliation_status": "flagged,manually_matched"},
            headers=auth_headers,
        )
        assert [t["reference"] for t in res.json()["data"]] == [flagged]

    @pytest.mark.asyncio
    async def test_dates_in_merchant_timezone(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        # 23:30 UTC on the 9th is 00:30 on the 10th in Lagos (UTC+1)
        await async_client.patch(
            "/settings", json={"timezone": "Africa/Lagos"}, headers=auth_headers
        )
        reference: str = await _payment(
            session_maker, created_at=datetime(2026, 10, 9, 23, 30, tzinfo=UTC)
        )

        res: Response = await async_client.get(
            "/transactions",
            params={"date_from": "2026-10-10", "date_to": "2026-10-10"},
            headers=auth_headers,
        )
        assert [t["reference"] for t in res.json()["data"]] == [reference]

        res = await async_client.get(
            "/transactions", params={"date_to": "2026-10-09"}, headers=auth_headers
        )
        assert res.json()["data"] == []

    @pytest.mark.asyncio
    async def test_dates_include_unpaid_attempts(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        day: datetime = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
        paid: str = await _payment(session_maker, created_at=day, paid_at=day)
        failed: str = await _payment(session_maker, status=TransactionStatus.FAILED, created_at=day)
        dates: dict = {"date_from": "2026-10-10", "date_to": "2026-10-10"}

        # all attempts started that day, whatever their status
        res: Response = await async_client.get("/transactions", params=dates, headers=auth_headers)
        assert {t["reference"] for t in res.json()["data"]} == {paid, failed}

        # status chooses paid or failed
        res = await async_client.get(
            "/transactions", params={**dates, "status": "success"}, headers=auth_headers
        )
        assert [t["reference"] for t in res.json()["data"]] == [paid]

        res = await async_client.get(
            "/transactions", params={**dates, "status": "failed,abandoned"}, headers=auth_headers
        )
        assert [t["reference"] for t in res.json()["data"]] == [failed]

    @pytest.mark.asyncio
    async def test_sort_by_amount(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        small: str = await _payment(session_maker, amount=1000)
        large: str = await _payment(session_maker, amount=9000)

        res: Response = await async_client.get(
            "/transactions", params={"sort": "-amount"}, headers=auth_headers
        )
        assert [t["reference"] for t in res.json()["data"]] == [large, small]

    @pytest.mark.asyncio
    async def test_only_own_transactions(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _payment(session_maker)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get("/transactions", headers=other_headers)
        assert res.json()["data"] == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            {"status": "settled"},
            {"date_from": "2026-10-10", "date_to": "2026-10-01"},
            {"sort": "reference"},
            {"limit": 101},
        ],
    )
    async def test_invalid_query(self, async_client: AsyncClient, auth_headers: dict, params):
        res: Response = await async_client.get("/transactions", params=params, headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"


class TestGetTransaction:
    @pytest.mark.asyncio
    async def test_detail_with_links(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers, order_number="A-1")
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        transaction_id: UUID = await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )
        await add_fulfillment(session_maker, merchant, UUID(order["id"]))
        dispute_id: UUID = await add_dispute(session_maker, merchant, transaction_id)
        reference: str = await _reference(session_maker, transaction_id)

        res: Response = await async_client.get(f"/transactions/{reference}", headers=auth_headers)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["reference"] == reference
        assert data["order"]["order_number"] == "A-1"
        assert data["order"]["status"] == "pending"
        assert len(data["fulfillments"]) == 1
        assert data["dispute"]["id"] == str(dispute_id)
        assert data["dispute"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_unlinked(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)

        res: Response = await async_client.get(f"/transactions/{reference}", headers=auth_headers)
        data: dict = res.json()["data"]

        assert data["order"] is None
        assert data["fulfillments"] == []
        assert data["dispute"] is None

    @pytest.mark.asyncio
    async def test_other_merchants_transaction(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get(f"/transactions/{reference}", headers=other_headers)

        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"


class TestMatch:
    @pytest.mark.asyncio
    async def test_match(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        reference: str = await _payment(
            session_maker,
            reconciliation_status=ReconciliationStatus.FLAGGED,
        )

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["order"]["id"] == order["id"]
        assert data["reconciliation_status"] == "manually_matched"
        assert data["reconciled_at"] is not None

        # the matched payment pays the order
        res = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)
        assert res.json()["data"]["status"] == "paid"
        assert res.json()["data"]["is_linked"] is True

    @pytest.mark.asyncio
    async def test_match_twice_is_harmless(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        reference: str = await _payment(session_maker)

        for _ in range(2):
            res: Response = await async_client.put(
                f"/transactions/{reference}/match",
                json={"order_id": order["id"]},
                headers=auth_headers,
            )
            assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_already_matched_to_another_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        first: dict = await _order(async_client, auth_headers)
        second: dict = await _order(async_client, auth_headers)
        reference: str = await _payment(session_maker, order_id=UUID(first["id"]))

        res: Response = await async_client.put(
            f"/transactions/{reference}/match",
            json={"order_id": second["id"]},
            headers=auth_headers,
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "MATCH_CONFLICT"
        assert res.json()["error"]["details"] == {"reason": "already_matched_to_another_order"}

    @pytest.mark.asyncio
    async def test_failed_payment(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        reference: str = await _payment(session_maker, status=TransactionStatus.FAILED)

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"reason": "transaction_not_successful"}

    @pytest.mark.asyncio
    async def test_cancelled_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        await async_client.delete(f"/orders/{order['id']}", headers=auth_headers)
        reference: str = await _payment(session_maker)

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"reason": "order_cancelled"}

    @pytest.mark.asyncio
    async def test_currency_mismatch(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers, currency="GHS")
        reference: str = await _payment(session_maker)

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"reason": "currency_mismatch"}

    @pytest.mark.asyncio
    async def test_paid_order_keeps_its_status(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        await set_order(session_maker, order["id"], status="fulfilled")
        reference: str = await _payment(session_maker)

        await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        res: Response = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)
        assert res.json()["data"]["status"] == "fulfilled"

    @pytest.mark.asyncio
    async def test_other_merchants_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )
        other_order: dict = await _order(async_client, other_headers)

        res: Response = await async_client.put(
            f"/transactions/{reference}/match",
            json={"order_id": other_order["id"]},
            headers=auth_headers,
        )

        assert res.status_code == 404


class TestFlag:
    @pytest.mark.asyncio
    async def test_flag_and_unflag(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)

        res: Response = await async_client.put(
            f"/transactions/{reference}/flag",
            json={"reason": "Duplicate of T123"},
            headers=auth_headers,
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["reconciliation_status"] == "flagged"
        assert data["flag_reason"] == "Duplicate of T123"
        assert data["flagged_at"] is not None

        res = await async_client.put(f"/transactions/{reference}/unflag", headers=auth_headers)
        data = res.json()["data"]

        assert res.status_code == 200
        assert data["reconciliation_status"] == "unmatched"
        assert data["flag_reason"] is None
        assert data["flagged_at"] is None

    @pytest.mark.asyncio
    async def test_unflag_matched_payment(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        reference: str = await _payment(
            session_maker,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )
        await async_client.put(
            f"/transactions/{reference}/flag", json={"reason": "Wrong amount"}, headers=auth_headers
        )

        res: Response = await async_client.put(
            f"/transactions/{reference}/unflag", headers=auth_headers
        )

        # reviewed by the merchant while linked
        assert res.json()["data"]["reconciliation_status"] == "manually_matched"

    @pytest.mark.asyncio
    async def test_reflag_keeps_flagged_at(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)

        first: Response = await async_client.put(
            f"/transactions/{reference}/flag", json={"reason": "Check"}, headers=auth_headers
        )
        second: Response = await async_client.put(
            f"/transactions/{reference}/flag", json={"reason": "Still odd"}, headers=auth_headers
        )

        assert second.json()["data"]["flag_reason"] == "Still odd"
        assert second.json()["data"]["flagged_at"] == first.json()["data"]["flagged_at"]

    @pytest.mark.asyncio
    async def test_unflag_not_flagged(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        reference: str = await _payment(session_maker)

        res: Response = await async_client.put(
            f"/transactions/{reference}/unflag", headers=auth_headers
        )

        assert res.status_code == 200
        assert res.json()["data"]["reconciliation_status"] == "unmatched"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": "x" * 256}])
    async def test_invalid_reason(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        payload: dict,
    ):
        reference: str = await _payment(session_maker)

        res: Response = await async_client.put(
            f"/transactions/{reference}/flag", json=payload, headers=auth_headers
        )

        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_reference(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.put(
            "/transactions/T000/flag", json={"reason": "Check"}, headers=auth_headers
        )

        assert res.status_code == 404


class TestSync:
    @pytest.mark.asyncio
    async def test_sync(
        self, async_client: AsyncClient, auth_headers: dict, queued_syncs: MagicMock
    ):
        await async_client.post(
            "/auth/paystack/connect", json={"secret_key": TEST_SECRET_KEY}, headers=auth_headers
        )

        res: Response = await async_client.post("/transactions/sync", headers=auth_headers)

        assert res.status_code == 202
        assert res.json()["data"] == {"status": "queued", "last_sync_at": None}
        queued_syncs.assert_called_once()
        assert queued_syncs.call_args.kwargs["kwargs"]["initial"] is False

    @pytest.mark.asyncio
    async def test_not_connected(
        self, async_client: AsyncClient, auth_headers: dict, queued_syncs: MagicMock
    ):
        res: Response = await async_client.post("/transactions/sync", headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "PAYSTACK_NOT_CONNECTED"
        queued_syncs.assert_not_called()

    @pytest.mark.asyncio
    async def test_initial_sync_running(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_syncs: MagicMock,
    ):
        await async_client.post(
            "/auth/paystack/connect", json={"secret_key": TEST_SECRET_KEY}, headers=auth_headers
        )
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        async with session_maker() as session:
            await session.execute(
                update(MerchantOnboarding)
                .where(MerchantOnboarding.merchant_id == merchant)
                .values(initial_sync_status=InitialSyncStatus.IN_PROGRESS)
            )
            await session.commit()

        res: Response = await async_client.post("/transactions/sync", headers=auth_headers)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "SYNC_IN_PROGRESS"
        queued_syncs.assert_not_called()
