import hashlib
import hmac
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeStatus,
    NotificationMessageType,
    OrderSource,
    OrderStatus,
    ReconciliationStatus,
)
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.models.webhook_events import WebhookEvent
from app.core.security import Security
from app.worker.tasks import webhooks as webhook_tasks
from app.worker.tasks.webhooks import process_webhook_event
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import merchant_id
from tests.test_transaction_sync import _merchant
from tests.test_transaction_sync import _transaction as _paystack_transaction

SessionMaker = async_sessionmaker[AsyncSession]
SECRET_KEY: str = "sk_test_webhookkey0001"  # pragma: allowlist secret


def _sign(body: bytes, key: str = SECRET_KEY) -> str:
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


def _dispute(dispute_id: int = 900, **fields) -> dict:
    dispute: dict = {
        "id": dispute_id,
        "refund_amount": 500000,
        "currency": "NGN",
        "status": "awaiting-merchant-feedback",
        "resolution": None,
        "category": "chargeback",
        "note": None,
        "messages": [
            {
                "sender": "disputes@bank.example",
                "body": "Customer says the item never arrived",
                "createdAt": datetime.now(UTC).isoformat(),
            }
        ],
        "customer": {
            "id": 10207,
            "first_name": "Ada",
            "last_name": "Obi",
            "email": "ada@example.com",
            "customer_code": "CUS_ada",
            "phone": None,
        },
        "bin": "408408",
        "last4": "4081",
        "dueAt": (datetime.now(UTC) + timedelta(hours=16)).isoformat(),
        "createdAt": datetime.now(UTC).isoformat(),
        # as paystack sends it: the embedded transaction's customer is nearly empty
        "transaction": _paystack_transaction(
            dispute_id + 1, customer={"international_format_phone": None}
        ),
    }
    dispute.update(fields)
    return dispute


@pytest.fixture
def queued_webhooks():
    with patch.object(process_webhook_event, "apply_async") as apply_async:
        yield apply_async


async def _connect_key(session_maker: SessionMaker) -> UUID:
    """Give the signed in merchant a (fake) connected secret key"""
    merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
    encrypted: str = await Security().encrypt_secret_key(SECRET_KEY)
    async with session_maker() as session:
        await session.execute(
            update(Merchant).where(Merchant.id == merchant).values(paystack_secret_key=encrypted)
        )
        await session.commit()
    return merchant


async def _webhook_path(async_client: AsyncClient, headers: dict) -> str:
    res: Response = await async_client.get("/settings/webhook", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]["url"].split("/api/v1", 1)[1]


class TestWebhookSettings:
    @pytest.mark.asyncio
    async def test_url_is_created_once_and_rotates(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.get("/settings/webhook", headers=auth_headers)
        data: dict = res.json()["data"]
        assert "/api/v1/webhooks/paystack/wh_" in data["url"]
        assert data["active"] is False and data["last_received_at"] is None
        assert "charge.dispute.create" in data["events"]

        again: Response = await async_client.get("/settings/webhook", headers=auth_headers)
        assert again.json()["data"]["url"] == data["url"]

        rotated: Response = await async_client.post(
            "/settings/webhook/rotate", headers=auth_headers
        )
        assert rotated.json()["data"]["url"] != data["url"]


class TestReceive:
    @pytest.mark.asyncio
    async def test_unknown_url(self, async_client: AsyncClient):
        res: Response = await async_client.post("/webhooks/paystack/wh_nope", content=b"{}")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_bad_signature(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await _connect_key(session_maker)
        path: str = await _webhook_path(async_client, auth_headers)
        body: bytes = json.dumps({"event": "charge.dispute.create", "data": _dispute()}).encode()

        res: Response = await async_client.post(
            path, content=body, headers={"x-paystack-signature": _sign(body, "sk_test_other")}
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"

        res = await async_client.post(path, content=body)
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_dispute_is_stored_once_and_queued(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_webhooks: MagicMock,
    ):
        merchant: UUID = await _connect_key(session_maker)
        path: str = await _webhook_path(async_client, auth_headers)
        body: bytes = json.dumps({"event": "charge.dispute.create", "data": _dispute()}).encode()
        headers: dict = {"x-paystack-signature": _sign(body)}

        first: Response = await async_client.post(path, content=body, headers=headers)
        retry: Response = await async_client.post(path, content=body, headers=headers)

        assert first.status_code == 200 and retry.status_code == 200
        async with session_maker() as session:
            stored = await session.scalar(
                select(func.count(WebhookEvent.id)).where(WebhookEvent.merchant_id == merchant)
            )
            stamped = await session.scalar(
                select(Merchant.webhook_last_received_at).where(Merchant.id == merchant)
            )
        assert stored == 1
        assert stamped is not None
        # not processed yet, so paystack's retry queues it again (the task runs it once)
        assert queued_webhooks.call_count == 2

        res: Response = await async_client.get("/settings/webhook", headers=auth_headers)
        assert res.json()["data"]["active"] is True

    @pytest.mark.asyncio
    async def test_other_events_are_acknowledged_and_dropped(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_webhooks: MagicMock,
    ):
        await _connect_key(session_maker)
        path: str = await _webhook_path(async_client, auth_headers)
        body: bytes = json.dumps({"event": "transfer.success", "data": {"id": 1}}).encode()

        res: Response = await async_client.post(
            path, content=body, headers={"x-paystack-signature": _sign(body)}
        )

        assert res.status_code == 200
        queued_webhooks.assert_not_called()
        async with session_maker() as session:
            assert await session.scalar(select(func.count(WebhookEvent.id))) == 0


class TestProcess:
    @pytest.fixture
    def task_db(self, sync_db: Session):
        with (
            patch("app.worker.tasks.webhooks.sync_session", lambda: nullcontext(sync_db)),
            patch.object(webhook_tasks, "publish") as publish,
            patch("app.worker.services.dispute_alerts.publish", publish),
            patch("app.worker.services.notifications.send_email.apply_async") as email,
        ):
            sync_db.published = publish
            sync_db.emailed = email
            yield sync_db

    @staticmethod
    def _event(sync_db: Session, merchant: Merchant, name: str, data: dict) -> str:
        event = WebhookEvent(
            merchant_id=merchant.id,
            event=name,
            body_hash=hashlib.sha256(json.dumps(data).encode() + name.encode()).hexdigest(),
            payload={"event": name, "data": data},
        )
        sync_db.add(event)
        sync_db.commit()
        return str(event.id)

    @pytest.mark.asyncio
    async def test_dispute_created_with_its_payment(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)

        process_webhook_event(self._event(task_db, merchant, "charge.dispute.create", _dispute()))

        dispute: Dispute = task_db.scalar(select(Dispute).where(Dispute.merchant_id == merchant.id))
        transaction: Transaction = task_db.get(Transaction, dispute.transaction_id)
        assert transaction.paystack_transaction_id == 901
        assert dispute.paystack_dispute_id == 900
        assert dispute.status == DisputeStatus.PENDING
        assert dispute.paystack_status == "awaiting-merchant-feedback"
        assert dispute.reason_raw == "Customer says the item never arrived"
        assert dispute.paystack_reference == "ref-901"
        # the payment's customer came from the dispute's own customer object
        assert transaction.customer_email == "ada@example.com"

        types = [call.args[1] for call in task_db.published.call_args_list]
        assert "dispute.created" in types
        notification = task_db.scalar(
            select(NotificationLog).where(NotificationLog.merchant_id == merchant.id)
        )
        assert notification.message_type == NotificationMessageType.DISPUTE_ALERT
        assert notification.dispute_id == dispute.id
        assert task_db.emailed.call_count == 1

    @pytest.mark.asyncio
    async def test_runs_once(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        event_id: str = self._event(task_db, merchant, "charge.dispute.create", _dispute())

        process_webhook_event(event_id)
        process_webhook_event(event_id)

        assert task_db.emailed.call_count == 1

    @pytest.mark.asyncio
    async def test_resolved_in_merchants_favour(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        process_webhook_event(self._event(task_db, merchant, "charge.dispute.create", _dispute()))
        due_at = task_db.scalar(select(Dispute.due_at))

        resolved: dict = _dispute(
            status="resolved", resolution="declined", resolvedAt=datetime.now(UTC).isoformat()
        )
        del resolved["dueAt"]
        process_webhook_event(self._event(task_db, merchant, "charge.dispute.resolve", resolved))

        dispute: Dispute = task_db.scalar(select(Dispute))
        task_db.refresh(dispute)
        assert dispute.status == DisputeStatus.WON
        assert dispute.resolved_at is not None
        # a partial event keeps the deadline it had
        assert dispute.due_at == due_at
        messages = task_db.scalars(select(NotificationLog.message_type)).all()
        assert NotificationMessageType.DISPUTE_RESOLVED in messages

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("resolution", "status"),
        [
            ("auto-accepted", DisputeStatus.AUTO_ACCEPTED),
            ("merchant-accepted", DisputeStatus.LOST),
        ],
    )
    async def test_refunded_outcomes(
        self, task_db: Session, resolution: str, status: DisputeStatus
    ):
        merchant: Merchant = _merchant(task_db)
        resolved: dict = _dispute(status="resolved", resolution=resolution)
        process_webhook_event(self._event(task_db, merchant, "charge.dispute.resolve", resolved))

        assert task_db.scalar(select(Dispute.status)) == status

    @pytest.mark.asyncio
    async def test_reminder(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        process_webhook_event(self._event(task_db, merchant, "charge.dispute.remind", _dispute()))

        types = [call.args[1] for call in task_db.published.call_args_list]
        assert "deadline.warning" in types
        assert task_db.scalar(select(NotificationLog.message_type)) == (
            NotificationMessageType.DEADLINE_WARNING
        )

    @pytest.mark.asyncio
    async def test_successful_payment_is_stored_and_matched(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        paid_at: datetime = datetime.now(UTC) - timedelta(hours=1)
        order = Order(
            merchant_id=merchant.id,
            order_number="A-555",
            amount=500000,
            currency="NGN",
            source=OrderSource.WEBSITE,
            ordered_at=paid_at - timedelta(hours=1),
        )
        task_db.add(order)
        task_db.commit()

        payment: dict = _paystack_transaction(555, paid_at=paid_at.isoformat())
        process_webhook_event(self._event(task_db, merchant, "charge.success", payment))

        transaction: Transaction = task_db.scalar(
            select(Transaction).where(Transaction.merchant_id == merchant.id)
        )
        assert transaction.order_id == order.id
        assert transaction.reconciliation_status == ReconciliationStatus.AUTO_MATCHED
        task_db.refresh(order)
        assert order.status == OrderStatus.PAID
        types = [call.args[1] for call in task_db.published.call_args_list]
        assert types == ["transaction.synced", "reconciliation.updated"]


SAMPLES: dict = json.loads(
    (Path(__file__).parent / "fixtures" / "paystack_webhooks.json").read_text()
)


class TestPaystackSamples:
    """The payloads from paystack's webhook docs, unchanged"""

    task_db = TestProcess.task_db

    @staticmethod
    def _run(task_db: Session, merchant: Merchant, name: str):
        process_webhook_event(TestProcess._event(task_db, merchant, name, SAMPLES[name]["data"]))

    @pytest.mark.asyncio
    async def test_dispute_create(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        self._run(task_db, merchant, "charge.dispute.create")

        dispute: Dispute = task_db.scalar(select(Dispute))
        transaction: Transaction = task_db.get(Transaction, dispute.transaction_id)
        assert dispute.paystack_dispute_id == 358950
        assert dispute.amount == 5800
        assert dispute.status == DisputeStatus.PENDING
        assert dispute.paystack_status == "awaiting-merchant-feedback"
        assert dispute.paystack_category == "chargeback"
        assert dispute.reason_raw == "Customer complained about debit without value"
        assert dispute.due_at == datetime(2020, 11, 25, 18, 0, tzinfo=UTC)
        assert dispute.created_at == datetime(2020, 11, 24, 13, 46, 57, tzinfo=UTC)
        assert dispute.paystack_reference == "v3mjfgbnc19v97x"
        # stored from the embedded transaction, with the dispute's customer
        assert transaction.paystack_transaction_id == 896467688
        assert transaction.customer_email == "example@test.com"
        assert transaction.customer_name == "John Doe"
        assert transaction.metadata_ is None  # paystack sent ""

    @pytest.mark.asyncio
    async def test_dispute_remind_after_create(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        self._run(task_db, merchant, "charge.dispute.create")
        task_db.published.reset_mock()

        self._run(task_db, merchant, "charge.dispute.remind")

        assert task_db.scalar(select(func.count(Dispute.id))) == 1
        types = [call.args[1] for call in task_db.published.call_args_list]
        assert types == ["deadline.warning"]

    @pytest.mark.asyncio
    async def test_dispute_resolve_auto_accepted(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        # a dispute we never saw open: created straight from its resolution
        self._run(task_db, merchant, "charge.dispute.resolve")

        dispute: Dispute = task_db.scalar(select(Dispute))
        transaction: Transaction = task_db.get(Transaction, dispute.transaction_id)
        assert dispute.status == DisputeStatus.AUTO_ACCEPTED
        assert dispute.resolution == "auto_accepted"
        assert dispute.paystack_resolution == "auto-accepted"
        assert dispute.resolved_at == datetime(2020, 11, 24, 14, 0, 2, tzinfo=UTC)
        assert transaction.status.value == "reversed"

    @pytest.mark.asyncio
    async def test_charge_success(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)
        self._run(task_db, merchant, "charge.success")

        transaction: Transaction = task_db.scalar(select(Transaction))
        assert transaction.paystack_reference == "qTPrJoy9Bx"
        assert transaction.amount == 10000
        assert transaction.customer_email == "bojack@horseman.com"
        assert transaction.paid_at == datetime(2016, 9, 30, 21, 10, 19, tzinfo=UTC)
        assert transaction.metadata_ is None  # paystack sent 0
        assert transaction.paystack_fees is None


class TestSampleDelivery:
    @pytest.mark.asyncio
    async def test_signed_sample_is_accepted(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_webhooks: MagicMock,
    ):
        await _connect_key(session_maker)
        path: str = await _webhook_path(async_client, auth_headers)
        body: bytes = json.dumps(SAMPLES["charge.dispute.create"]).encode()

        res: Response = await async_client.post(
            path, content=body, headers={"x-paystack-signature": _sign(body)}
        )

        assert res.status_code == 200
        queued_webhooks.assert_called_once()
