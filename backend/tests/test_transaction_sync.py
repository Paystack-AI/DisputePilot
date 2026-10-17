from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest
from celery.exceptions import Reject, Retry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackClient, PaystackUpstreamError
from app.api.models.customers import Customer
from app.api.models.enums import (
    InitialSyncStatus,
    OnboardingStep,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
)
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchants import Merchant
from app.api.models.transactions import Transaction
from app.worker.services.transaction_sync import (
    TransactionSync,
    mark_initial_sync_failed,
    merchants_due_for_sync,
)
from app.worker.tasks.transaction_sync import sync_transactions

MERCHANT_EMAIL: str = "owner@acme.example"
STARTED_AT: datetime = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def _transaction(paystack_id: int, **fields) -> dict:
    transaction: dict = {
        "id": paystack_id,
        "reference": f"ref-{paystack_id}",
        "amount": 500000,
        "currency": "NGN",
        "channel": "card",
        "status": "success",
        "paid_at": "2026-10-10T12:00:00.000Z",
        "created_at": "2026-10-10T11:59:00.000Z",
        "fees": 7500,
        "metadata": {"order_number": f"A-{paystack_id}"},
        "customer": {
            "email": "Ada@Example.com",
            "first_name": "Ada",
            "last_name": "Obi",
            "customer_code": "CUS_ada",
            "phone": "08012345678",
        },
    }
    transaction.update(fields)
    return transaction


class FakePaystackPages:
    """GET /transaction answered from a list of pages (one list of transactions each)"""

    def __init__(self, pages: list[list[dict]] | None = None, status_code: int = 200):
        self.pages = pages if pages is not None else [[]]
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"status": False, "message": "down"})

        page: int = int(request.url.params["page"])
        data: list[dict] = self.pages[page - 1]
        return httpx.Response(
            200,
            json={
                "status": True,
                "message": "ok",
                "data": data,
                "meta": {
                    "total": sum(len(p) for p in self.pages),
                    "page": page,
                    "pageCount": len(self.pages),
                },
            },
        )


def _client(fake: FakePaystackPages) -> PaystackClient:
    http = httpx.Client(transport=httpx.MockTransport(fake), base_url="https://api.paystack.co")
    return PaystackClient("sk_test_fakekey01", http)  # pragma: allowlist secret


def _merchant(sync_db: Session, **fields) -> Merchant:
    merchant = Merchant(
        email=MERCHANT_EMAIL,
        business_name="Acme",
        is_verified=True,
        is_active=True,
        **fields,
    )
    sync_db.add(merchant)
    sync_db.flush()
    sync_db.add(
        MerchantOnboarding(
            merchant_id=merchant.id,
            current_step=OnboardingStep.INITIAL_SYNC,
            initial_sync_status=InitialSyncStatus.IN_PROGRESS,
        )
    )
    sync_db.commit()
    return merchant


def _onboarding(sync_db: Session, merchant: Merchant) -> MerchantOnboarding:
    return sync_db.scalar(
        select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant.id)
    )


def _transactions(sync_db: Session, merchant: Merchant) -> list[Transaction]:
    return list(
        sync_db.scalars(
            select(Transaction)
            .where(Transaction.merchant_id == merchant.id)
            .order_by(Transaction.paystack_transaction_id)
        )
    )


class TestInitialSync:
    @pytest.mark.asyncio
    async def test_stores_transactions_and_completes_onboarding(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages([[_transaction(1), _transaction(2)]])

        stored: int = TransactionSync(sync_db, _client(fake), merchant).run(
            initial=True, started_at=STARTED_AT
        )

        assert stored == 2
        first, second = _transactions(sync_db, merchant)
        assert first.paystack_reference == "ref-1"
        assert first.amount == 500000
        assert first.channel == TransactionChannel.CARD
        assert first.status == TransactionStatus.SUCCESS
        assert first.paystack_fees == 7500
        assert first.customer_email == "ada@example.com"
        assert first.customer_name == "Ada Obi"
        assert first.metadata_ == {"order_number": "A-1"}
        assert first.reconciliation_status == ReconciliationStatus.UNMATCHED
        # both payments belong to the one customer
        assert first.customer_id is not None
        assert first.customer_id == second.customer_id

        onboarding: MerchantOnboarding = _onboarding(sync_db, merchant)
        assert onboarding.initial_sync_status == InitialSyncStatus.COMPLETED
        assert onboarding.current_step == OnboardingStep.FIRST_RECONCILIATION
        assert onboarding.initial_sync_total == 2
        assert onboarding.initial_sync_processed == 2

        sync_db.refresh(merchant)
        assert merchant.last_transaction_sync_at == STARTED_AT

    @pytest.mark.asyncio
    async def test_window_is_last_30_days(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages()

        TransactionSync(sync_db, _client(fake), merchant).run(initial=True, started_at=STARTED_AT)

        params = fake.requests[0].url.params
        assert params["from"] == (STARTED_AT - timedelta(days=30)).isoformat()
        assert params["to"] == STARTED_AT.isoformat()

    @pytest.mark.asyncio
    async def test_fetches_every_page(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages([[_transaction(1)], [_transaction(2)], [_transaction(3)]])

        stored: int = TransactionSync(sync_db, _client(fake), merchant).run(
            initial=True, started_at=STARTED_AT
        )

        assert stored == 3
        assert [r.url.params["page"] for r in fake.requests] == ["1", "2", "3"]
        assert _onboarding(sync_db, merchant).initial_sync_processed == 3


class TestResync:
    @pytest.mark.asyncio
    async def test_window_starts_at_last_sync(self, sync_db: Session):
        last_sync: datetime = STARTED_AT - timedelta(days=1)
        merchant: Merchant = _merchant(sync_db, last_transaction_sync_at=last_sync)
        fake = FakePaystackPages()

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        assert fake.requests[0].url.params["from"] == last_sync.isoformat()
        sync_db.refresh(merchant)
        assert merchant.last_transaction_sync_at == STARTED_AT

    @pytest.mark.asyncio
    async def test_never_synced_falls_back_to_30_days(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages()

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        assert fake.requests[0].url.params["from"] == (STARTED_AT - timedelta(days=30)).isoformat()

    @pytest.mark.asyncio
    async def test_resync_leaves_onboarding_alone(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)

        TransactionSync(sync_db, _client(FakePaystackPages()), merchant).run(
            initial=False, started_at=STARTED_AT
        )

        assert _onboarding(sync_db, merchant).initial_sync_status == InitialSyncStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_resyncing_updates_paystack_fields_only(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        TransactionSync(sync_db, _client(FakePaystackPages([[_transaction(1)]])), merchant).run(
            initial=False, started_at=STARTED_AT
        )
        (transaction,) = _transactions(sync_db, merchant)
        transaction.reconciliation_status = ReconciliationStatus.MANUALLY_MATCHED
        sync_db.commit()

        TransactionSync(
            sync_db, _client(FakePaystackPages([[_transaction(1, status="reversed")]])), merchant
        ).run(initial=False, started_at=STARTED_AT + timedelta(days=1))

        (transaction,) = _transactions(sync_db, merchant)
        sync_db.refresh(transaction)
        assert transaction.status == TransactionStatus.REVERSED
        # the app's own fields are kept
        assert transaction.reconciliation_status == ReconciliationStatus.MANUALLY_MATCHED

    @pytest.mark.asyncio
    async def test_failed_sync_keeps_last_sync(self, sync_db: Session):
        last_sync: datetime = STARTED_AT - timedelta(days=1)
        merchant: Merchant = _merchant(sync_db, last_transaction_sync_at=last_sync)

        with pytest.raises(PaystackUpstreamError):
            TransactionSync(sync_db, _client(FakePaystackPages(status_code=500)), merchant).run(
                initial=False, started_at=STARTED_AT
            )

        sync_db.rollback()
        sync_db.refresh(merchant)
        assert merchant.last_transaction_sync_at == last_sync


class TestMapping:
    @pytest.mark.asyncio
    async def test_channels(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages(
            [
                [
                    _transaction(1, channel="dedicated_nuban"),
                    _transaction(2, channel="bank"),
                    _transaction(3, channel="capitec_pay"),
                ]
            ]
        )

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        assert [t.channel for t in _transactions(sync_db, merchant)] == [
            TransactionChannel.BANK_TRANSFER,
            TransactionChannel.BANK,
            TransactionChannel.OTHER,
        ]

    @pytest.mark.asyncio
    async def test_unknown_currency_is_skipped(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages([[_transaction(1), _transaction(2, currency="EGP")]])

        stored: int = TransactionSync(sync_db, _client(fake), merchant).run(
            initial=False, started_at=STARTED_AT
        )

        assert stored == 1
        assert [t.paystack_transaction_id for t in _transactions(sync_db, merchant)] == [1]

    @pytest.mark.asyncio
    async def test_empty_metadata(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages([[_transaction(1, metadata="")]])

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        assert _transactions(sync_db, merchant)[0].metadata_ is None


class TestCustomers:
    @pytest.mark.asyncio
    async def test_customer_created_from_paystack(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages([[_transaction(1)]])

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        customer: Customer = sync_db.scalar(
            select(Customer).where(Customer.merchant_id == merchant.id)
        )
        assert customer.email == "ada@example.com"
        assert customer.name == "Ada Obi"
        assert customer.paystack_customer_code == "CUS_ada"
        assert customer.is_shared is False
        assert customer.first_seen_at == datetime(2026, 10, 10, 11, 59, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_merchant_entered_details_are_kept(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        sync_db.add(Customer(merchant_id=merchant.id, email="ada@example.com", name="Ada (VIP)"))
        sync_db.commit()

        TransactionSync(sync_db, _client(FakePaystackPages([[_transaction(1)]])), merchant).run(
            initial=False, started_at=STARTED_AT
        )

        (customer,) = sync_db.scalars(select(Customer).where(Customer.merchant_id == merchant.id))
        sync_db.refresh(customer)
        assert customer.name == "Ada (VIP)"
        # gaps are filled in
        assert customer.paystack_customer_code == "CUS_ada"

    @pytest.mark.asyncio
    async def test_merchant_email_is_shared(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        fake = FakePaystackPages(
            [[_transaction(1, customer={"email": MERCHANT_EMAIL, "customer_code": "CUS_me"})]]
        )

        TransactionSync(sync_db, _client(fake), merchant).run(initial=False, started_at=STARTED_AT)

        customer: Customer = sync_db.scalar(
            select(Customer).where(Customer.merchant_id == merchant.id)
        )
        assert customer.is_shared is True

    @pytest.mark.asyncio
    async def test_customer_code_on_another_customer(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        sync_db.add(
            Customer(
                merchant_id=merchant.id, email="old@example.com", paystack_customer_code="CUS_ada"
            )
        )
        sync_db.commit()

        # same paystack customer, new email: linked by email, the code stays put
        TransactionSync(sync_db, _client(FakePaystackPages([[_transaction(1)]])), merchant).run(
            initial=False, started_at=STARTED_AT
        )

        (transaction,) = _transactions(sync_db, merchant)
        customer: Customer = sync_db.get(Customer, transaction.customer_id)
        assert customer.email == "ada@example.com"
        assert customer.paystack_customer_code is None


class TestScheduling:
    @pytest.mark.asyncio
    async def test_merchants_due_for_sync(self, sync_db: Session):
        due: Merchant = _merchant(sync_db, paystack_secret_key="encrypted")
        _onboarding(sync_db, due).initial_sync_status = InitialSyncStatus.COMPLETED
        sync_db.commit()

        assert due.id in merchants_due_for_sync(sync_db)

    @pytest.mark.asyncio
    async def test_initial_sync_not_done_is_not_due(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db, paystack_secret_key="encrypted")

        assert merchant.id not in merchants_due_for_sync(sync_db)

    @pytest.mark.asyncio
    async def test_mark_initial_sync_failed(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)

        mark_initial_sync_failed(sync_db, merchant.id)

        assert _onboarding(sync_db, merchant).initial_sync_status == InitialSyncStatus.FAILED


class TestTask:
    @pytest.fixture
    def task_db(self, sync_db: Session):
        with patch("app.worker.tasks.transaction_sync.sync_session", lambda: nullcontext(sync_db)):
            yield sync_db

    @pytest.fixture
    def retry(self):
        with patch.object(sync_transactions, "retry", side_effect=Retry()) as task_retry:
            yield task_retry

    @pytest.mark.asyncio
    async def test_not_connected_is_skipped(self, task_db: Session):
        merchant: Merchant = _merchant(task_db)

        with patch("app.worker.tasks.transaction_sync.TransactionSync") as transaction_sync:
            sync_transactions(str(merchant.id), initial=True)

        transaction_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_paystack_down_retries(self, task_db: Session, retry: MagicMock):
        merchant: Merchant = _merchant(task_db, paystack_secret_key="encrypted")

        with (
            patch("app.worker.tasks.transaction_sync.SECURITY.decrypt_secret_key_sync"),
            patch(
                "app.worker.tasks.transaction_sync.TransactionSync.run",
                side_effect=PaystackUpstreamError("down", 503),
            ),
            pytest.raises(Retry),
        ):
            sync_transactions(str(merchant.id), initial=True)

        # still in progress: a retry is coming
        assert _onboarding(task_db, merchant).initial_sync_status == InitialSyncStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_permanent_failure_fails_initial_sync(self, task_db: Session, retry: MagicMock):
        merchant: Merchant = _merchant(task_db, paystack_secret_key="encrypted")

        with (
            patch("app.worker.tasks.transaction_sync.SECURITY.decrypt_secret_key_sync"),
            patch(
                "app.worker.tasks.transaction_sync.TransactionSync.run",
                side_effect=ValueError("bad data"),
            ),
            pytest.raises(Reject),
        ):
            sync_transactions(str(merchant.id), initial=True)

        retry.assert_not_called()
        assert _onboarding(task_db, merchant).initial_sync_status == InitialSyncStatus.FAILED
