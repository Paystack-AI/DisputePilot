from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.enums import DisputeStatus, InitialSyncStatus, NotificationMessageType
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.repo.disputes import SyncDisputeRepository
from app.worker.tasks.disputes import poll_disputes, watch_deadlines
from tests.test_transaction_sync import _merchant, _onboarding
from tests.test_webhooks import _dispute


def _connected(sync_db: Session, email: str = "owner@acme.example", **fields) -> Merchant:
    merchant: Merchant = _merchant(sync_db, paystack_secret_key="encrypted", **fields)
    if email != "owner@acme.example":
        merchant.email = email
    _onboarding(sync_db, merchant).initial_sync_status = InitialSyncStatus.COMPLETED
    sync_db.commit()
    return merchant


@pytest.fixture
def jobs_db(sync_db: Session):
    with (
        patch("app.worker.tasks.disputes.sync_session", lambda: nullcontext(sync_db)),
        patch("app.worker.tasks.disputes.SECURITY.decrypt_secret_key_sync", return_value="sk"),
        patch("app.worker.services.dispute_alerts.publish") as publish,
        patch("app.worker.services.notifications.send_email.apply_async") as email,
    ):
        sync_db.published = publish
        sync_db.emailed = email
        yield sync_db


@pytest.fixture
def paystack():
    client = MagicMock()
    client.list_disputes.return_value = {"data": [], "meta": {"pageCount": 1}}
    with patch("app.worker.tasks.disputes.PaystackClient", return_value=client):
        yield client


def _messages(sync_db: Session) -> list[NotificationMessageType]:
    return list(sync_db.scalars(select(NotificationLog.message_type)))


class TestMerchantsToPoll:
    @pytest.mark.asyncio
    async def test_webhook_merchants_are_skipped(self, sync_db: Session):
        quiet = _connected(sync_db)
        sync_db.add(quiet)
        now: datetime = datetime.now(UTC)
        quiet.webhook_last_received_at = now - timedelta(days=3)
        sync_db.commit()

        due = SyncDisputeRepository(sync_db).merchants_to_poll(now - timedelta(hours=24))
        assert due == [quiet.id]

        quiet.webhook_last_received_at = now - timedelta(minutes=5)
        sync_db.commit()
        assert SyncDisputeRepository(sync_db).merchants_to_poll(now - timedelta(hours=24)) == []


class TestPoll:
    @pytest.mark.asyncio
    async def test_new_dispute_is_taken_in_once(self, jobs_db: Session, paystack: MagicMock):
        merchant: Merchant = _connected(jobs_db)
        paystack.list_disputes.return_value = {"data": [_dispute()], "meta": {"pageCount": 1}}

        assert poll_disputes(str(merchant.id)) == 1
        poll_disputes(str(merchant.id))

        assert jobs_db.scalar(select(Dispute.paystack_dispute_id)) == 900
        # alerted on the first poll only
        assert _messages(jobs_db) == [NotificationMessageType.DISPUTE_ALERT]
        types = [call.args[1] for call in jobs_db.published.call_args_list]
        assert types == ["dispute.created"]

    @pytest.mark.asyncio
    async def test_open_dispute_resolved_since(self, jobs_db: Session, paystack: MagicMock):
        merchant: Merchant = _connected(jobs_db)
        paystack.list_disputes.return_value = {"data": [_dispute()], "meta": {"pageCount": 1}}
        poll_disputes(str(merchant.id))

        # no longer awaiting the merchant: fetched by id
        paystack.list_disputes.return_value = {"data": [], "meta": {"pageCount": 1}}
        paystack.fetch_dispute.return_value = {
            "data": _dispute(status="resolved", resolution="declined")
        }
        poll_disputes(str(merchant.id))

        paystack.fetch_dispute.assert_called_once_with(900)
        assert jobs_db.scalar(select(Dispute.status)) == DisputeStatus.WON
        assert NotificationMessageType.DISPUTE_RESOLVED in _messages(jobs_db)

        # resolved ones are not fetched again
        poll_disputes(str(merchant.id))
        paystack.fetch_dispute.assert_called_once()


class TestDeadlineWatcher:
    @staticmethod
    def _open_dispute(jobs_db: Session, paystack: MagicMock, due_in: timedelta) -> Dispute:
        merchant: Merchant = _connected(jobs_db)
        due_at: str = (datetime.now(UTC) + due_in).isoformat()
        paystack.list_disputes.return_value = {
            "data": [_dispute(dueAt=due_at)],
            "meta": {"pageCount": 1},
        }
        poll_disputes(str(merchant.id))
        jobs_db.published.reset_mock()
        return jobs_db.scalar(select(Dispute))

    @pytest.mark.asyncio
    async def test_warnings_at_8_and_4_hours_once_each(self, jobs_db: Session, paystack: MagicMock):
        dispute: Dispute = self._open_dispute(jobs_db, paystack, timedelta(hours=7))

        assert watch_deadlines() == 1
        assert watch_deadlines() == 0
        assert dispute.last_deadline_warning_hours == 8

        dispute.due_at = datetime.now(UTC) + timedelta(hours=3)
        jobs_db.commit()
        assert watch_deadlines() == 1
        assert watch_deadlines() == 0
        assert dispute.last_deadline_warning_hours == 4

        warnings = [
            call.args[2]["hours_remaining"]
            for call in jobs_db.published.call_args_list
            if call.args[1] == "deadline.warning"
        ]
        assert warnings == [7, 3]
        assert _messages(jobs_db).count(NotificationMessageType.DEADLINE_WARNING) == 2

    @pytest.mark.asyncio
    async def test_far_off_and_submitted_disputes_are_left_alone(
        self, jobs_db: Session, paystack: MagicMock
    ):
        dispute: Dispute = self._open_dispute(jobs_db, paystack, timedelta(hours=12))
        assert watch_deadlines() == 0

        dispute.due_at = datetime.now(UTC) + timedelta(hours=2)
        dispute.status = DisputeStatus.SUBMITTED
        jobs_db.commit()
        assert watch_deadlines() == 0
