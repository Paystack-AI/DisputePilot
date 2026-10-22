from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.api.models.enums import (
    NotificationMessageType,
    NotificationStatus,
    OnboardingStep,
    OrderStatus,
    ReconciliationStatus,
)
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.notifications_log import NotificationLog
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.services.reconciliation_engine import auto_match_after_sync
from app.worker.services.transaction_sync import TransactionSync
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_transaction, merchant_id, set_order
from tests.test_transaction_sync import FakePaystackPages, _client, _merchant
from tests.test_transaction_sync import _transaction as _paystack_transaction

SessionMaker = async_sessionmaker[AsyncSession]


async def _merchant_id(session_maker: SessionMaker) -> UUID:
    return await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])


async def _order(async_client: AsyncClient, headers: dict, **fields) -> dict:
    res: Response = await async_client.post(
        "/orders", json={"amount": 4500000, **fields}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def _payment(session_maker: SessionMaker, **fields) -> UUID:
    return await add_transaction(session_maker, await _merchant_id(session_maker), **fields)


async def _start(async_client: AsyncClient, headers: dict, status: int = 201) -> dict:
    res: Response = await async_client.post("/reconciliation/start", json={}, headers=headers)
    assert res.status_code == status, res.text
    return res.json()["data"]


async def _transaction(session_maker: SessionMaker, transaction_id: UUID) -> Transaction:
    async with session_maker() as session:
        return await session.get(Transaction, transaction_id)


async def _order_row(session_maker: SessionMaker, order_id: str) -> Order:
    async with session_maker() as session:
        return await session.get(Order, UUID(order_id))


class TestStart:
    @pytest.mark.asyncio
    async def test_matches_and_categorises(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        by_number = await _order(async_client, auth_headers, order_number="A-1032")
        suggested = await _order(async_client, auth_headers, amount=2000000)
        await _order(async_client, auth_headers, amount=999900)  # nothing paid it
        await _payment(session_maker, reference="A-1032")
        await _payment(session_maker, amount=2000000)
        await _payment(session_maker, amount=777700)  # no order

        view: dict = await _start(async_client, auth_headers)

        assert view["session"]["status"] == "in_progress"
        assert view["session"]["totals"] == {
            "total_transactions": 3,
            "matched": 1,
            "suggested": 1,
            "unmatched_payments": 1,
            "flagged": 0,
            "unmatched_orders": 1,
        }
        matched: dict = view["matched"][0]
        assert matched["order"]["id"] == by_number["id"]
        assert (matched["tier"], matched["confidence"]) == (1, 100)
        assert matched["transaction"]["reconciliation_status"] == "auto_matched"
        assert matched["order"]["status"] == "paid"

        suggestion: dict = view["suggestions"][0]
        assert suggestion["order"]["id"] == suggested["id"]
        assert suggestion["tier"] == 3
        assert suggestion["confidence_tier"] == "likely"
        assert suggestion["reasoning"].startswith("Amount identical")
        assert view["unmatched_payments"][0]["amount"] == 777700
        assert view["unmatched_orders"][0]["amount"] == 999900

    @pytest.mark.asyncio
    async def test_amount_mismatch_is_flagged(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _order(async_client, auth_headers, order_number="A-1", amount=4000000)
        await _payment(session_maker, reference="A-1")

        view: dict = await _start(async_client, auth_headers)

        assert view["flagged"][0]["reason"] == "amount_mismatch"
        assert view["session"]["totals"]["flagged"] == 1

    @pytest.mark.asyncio
    async def test_tier2_by_customer(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, customer_email="ada@example.com")
        payment = await _payment(session_maker, customer_id=UUID(order["customer"]["id"]))

        view: dict = await _start(async_client, auth_headers)

        assert view["matched"][0]["tier"] == 2
        assert (await _transaction(session_maker, payment)).order_id == UUID(order["id"])

    @pytest.mark.asyncio
    async def test_open_session_is_continued(self, async_client: AsyncClient, auth_headers: dict):
        first: dict = await _start(async_client, auth_headers)
        again: dict = await _start(async_client, auth_headers, status=200)
        assert again["session"]["id"] == first["session"]["id"]

    @pytest.mark.asyncio
    async def test_range_validation(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.post(
            "/reconciliation/start",
            json={"date_range_start": "2026-10-01", "date_range_end": "2026-11-15"},
            headers=auth_headers,
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_finishes_onboarding(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant_id(session_maker)
        async with session_maker() as session:
            onboarding = await session.scalar(
                select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant)
            )
            onboarding.current_step = OnboardingStep.FIRST_RECONCILIATION
            await session.commit()

        await _start(async_client, auth_headers)

        async with session_maker() as session:
            onboarding = await session.scalar(
                select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant)
            )
            assert onboarding.current_step == OnboardingStep.COMPLETED
            assert not onboarding.first_reconciliation_skipped

    @pytest.mark.asyncio
    async def test_needs_auth(self, async_client: AsyncClient):
        res: Response = await async_client.post("/reconciliation/start", json={})
        assert res.status_code == 401


class TestDecisions:
    @pytest.mark.asyncio
    async def test_accept_suggestion(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers)
        payment = await _payment(session_maker)
        await _start(async_client, auth_headers)
        decision: dict = {"transaction_id": str(payment), "order_id": order["id"]}

        res: Response = await async_client.post(
            "/reconciliation/accept-match", json=decision, headers=auth_headers
        )

        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        assert data["transaction"]["reconciliation_status"] == "manually_matched"
        assert data["totals"]["matched"] == 1 and data["totals"]["suggested"] == 0
        assert (await _order_row(session_maker, order["id"])).status == OrderStatus.PAID
        stored = await _transaction(session_maker, payment)
        assert (stored.match_tier, stored.match_confidence) == (3, 90)

        # retrying is safe
        res = await async_client.post(
            "/reconciliation/accept-match", json=decision, headers=auth_headers
        )
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_accept_without_suggestion(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, amount=100000)
        payment = await _payment(session_maker)

        res: Response = await async_client.post(
            "/reconciliation/accept-match",
            json={"transaction_id": str(payment), "order_id": order["id"]},
            headers=auth_headers,
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_suggestion_is_not_suggested_again(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers)
        payment = await _payment(session_maker)
        await _start(async_client, auth_headers)

        res: Response = await async_client.post(
            "/reconciliation/reject-match",
            json={"transaction_id": str(payment), "order_id": order["id"]},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["totals"]["unmatched_payments"] == 1

        view: dict = await _start(async_client, auth_headers, status=200)
        assert view["suggestions"] == []
        assert len(view["unmatched_payments"]) == 1

    @pytest.mark.asyncio
    async def test_reject_automatic_match(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, order_number="A-7")
        payment = await _payment(session_maker, reference="A-7")
        await _start(async_client, auth_headers)

        res: Response = await async_client.post(
            "/reconciliation/reject-match",
            json={"transaction_id": str(payment), "order_id": order["id"]},
            headers=auth_headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["data"]["transaction"]["reconciliation_status"] == "unmatched"
        assert (await _order_row(session_maker, order["id"])).status == OrderStatus.PENDING

        # the next pass leaves the pair alone
        view: dict = await _start(async_client, auth_headers, status=200)
        assert view["matched"] == [] and view["suggestions"] == []

    @pytest.mark.asyncio
    async def test_reject_fulfilled_automatic_match(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, order_number="A-8")
        payment = await _payment(session_maker, reference="A-8")
        await _start(async_client, auth_headers)
        await set_order(session_maker, order["id"], status=OrderStatus.FULFILLED)

        res: Response = await async_client.post(
            "/reconciliation/reject-match",
            json={"transaction_id": str(payment), "order_id": order["id"]},
            headers=auth_headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["details"]["reason"] == "order_fulfilled"

    @pytest.mark.asyncio
    async def test_other_merchants_rows_are_missing(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.post(
            "/reconciliation/reject-match",
            json={
                "transaction_id": "01900000-0000-7000-8000-000000000001",
                "order_id": "01900000-0000-7000-8000-000000000002",
            },
            headers=auth_headers,
        )
        assert res.status_code == 404


class TestComplete:
    @pytest.mark.asyncio
    async def test_saves_counts_and_emails_summary(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_emails,
    ):
        await _order(async_client, auth_headers, order_number="A-1")
        await _payment(session_maker, reference="A-1")
        await _payment(session_maker, amount=123400)
        await _start(async_client, auth_headers)
        queued_emails.reset_mock()

        res: Response = await async_client.post("/reconciliation/complete", headers=auth_headers)

        assert res.status_code == 200, res.text
        session: dict = res.json()["data"]
        assert session["status"] == "completed"
        assert session["totals"]["matched"] == 1
        assert session["totals"]["unmatched_payments"] == 1

        kwargs: dict = queued_emails.call_args.kwargs["kwargs"]
        assert kwargs["recipient_email"] == SIGN_UP_PAYLOAD["email"]
        assert "Reconciliation" in kwargs["subject"]
        async with session_maker() as db:
            notification = await db.get(NotificationLog, UUID(kwargs["notification_id"]))
        assert notification.message_type == NotificationMessageType.RECONCILIATION_SUMMARY
        assert notification.status == NotificationStatus.PENDING
        assert notification.metadata_["session_id"] == session["id"]

        # nothing is open now; current shows the completed one
        res = await async_client.post("/reconciliation/complete", headers=auth_headers)
        assert res.status_code == 404
        res = await async_client.get("/reconciliation/current", headers=auth_headers)
        assert res.json()["data"]["session"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_no_email_when_turned_off(
        self, async_client: AsyncClient, auth_headers: dict, queued_emails
    ):
        res: Response = await async_client.patch(
            "/settings", json={"notification_email": False}, headers=auth_headers
        )
        assert res.status_code == 200, res.text
        await _start(async_client, auth_headers)
        queued_emails.reset_mock()

        res = await async_client.post("/reconciliation/complete", headers=auth_headers)

        assert res.status_code == 200
        queued_emails.assert_not_called()


class TestReads:
    @pytest.mark.asyncio
    async def test_current_before_any_session(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/reconciliation/current", headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_sessions_list_and_detail(self, async_client: AsyncClient, auth_headers: dict):
        started: dict = await _start(async_client, auth_headers)

        res: Response = await async_client.get("/reconciliation/sessions", headers=auth_headers)
        assert res.status_code == 200
        assert [s["id"] for s in res.json()["data"]] == [started["session"]["id"]]
        assert res.json()["meta"]["total"] == 1

        res = await async_client.get(
            f"/reconciliation/sessions/{started['session']['id']}", headers=auth_headers
        )
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_summary(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _order(async_client, auth_headers, order_number="A-1")
        await _payment(session_maker, reference="A-1")
        await _payment(session_maker, amount=123400)
        await _start(async_client, auth_headers)

        res: Response = await async_client.get("/reconciliation/summary", headers=auth_headers)

        assert res.json()["data"] == {
            "synced_today": 2,
            "matched_today": 1,
            "needs_review": 1,
            "last_completed_at": None,
        }


class TestOrderActions:
    @pytest.mark.asyncio
    async def test_cash_payment(self, async_client: AsyncClient, auth_headers: dict):
        order = await _order(async_client, auth_headers)

        res: Response = await async_client.put(
            f"/orders/{order['id']}/resolve",
            json={"resolution": "cash_payment"},
            headers=auth_headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["data"]["status"] == "paid"
        assert res.json()["data"]["resolution"] == "cash_payment"

    @pytest.mark.asyncio
    async def test_payment_failed(self, async_client: AsyncClient, auth_headers: dict):
        order = await _order(async_client, auth_headers)

        res: Response = await async_client.put(
            f"/orders/{order['id']}/resolve",
            json={"resolution": "payment_failed"},
            headers=auth_headers,
        )

        assert res.json()["data"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_linked_order_can_not_be_resolved(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, order_number="A-2")
        await _payment(session_maker, reference="A-2")
        await _start(async_client, auth_headers)

        res: Response = await async_client.put(
            f"/orders/{order['id']}/resolve",
            json={"resolution": "cash_payment"},
            headers=auth_headers,
        )
        assert res.status_code == 409

    @pytest.mark.asyncio
    async def test_flagged_order_is_left_out_of_matching(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order = await _order(async_client, auth_headers, order_number="A-3")
        await _payment(session_maker, reference="A-3")

        res: Response = await async_client.put(
            f"/orders/{order['id']}/flag", json={"reason": "duplicate"}, headers=auth_headers
        )
        assert res.status_code == 200
        assert res.json()["data"]["flag_reason"] == "duplicate"

        view: dict = await _start(async_client, auth_headers)
        assert view["matched"] == []
        assert view["flagged_orders"][0]["reason"] == "duplicate"

        res = await async_client.put(f"/orders/{order['id']}/unflag", headers=auth_headers)
        assert res.json()["data"]["flagged_at"] is None
        view = await _start(async_client, auth_headers, status=200)
        assert len(view["matched"]) == 1


class TestAutomaticPass:
    @pytest.mark.asyncio
    async def test_after_sync(self, sync_db: Session):
        merchant = _merchant(sync_db)
        paid_at: datetime = datetime.now(UTC) - timedelta(days=1)
        order = Order(
            merchant_id=merchant.id,
            order_number="A-77",
            amount=500000,
            currency="NGN",
            source="website",
            ordered_at=paid_at - timedelta(hours=2),
        )
        sync_db.add(order)
        sync_db.commit()

        fake = FakePaystackPages(
            [[_paystack_transaction(77, paid_at=paid_at.isoformat().replace("+00:00", "Z"))]]
        )
        TransactionSync(sync_db, _client(fake), merchant).run(initial=True)

        outcome = auto_match_after_sync(sync_db, merchant.id)
        sync_db.commit()

        assert outcome.matched == 1
        transaction = sync_db.scalar(
            select(Transaction).where(Transaction.merchant_id == merchant.id)
        )
        assert transaction.order_id == order.id
        assert transaction.reconciliation_status == ReconciliationStatus.AUTO_MATCHED
        sync_db.refresh(order)
        assert order.status == OrderStatus.PAID

        # running again changes nothing
        assert not auto_match_after_sync(sync_db, merchant.id).changed
