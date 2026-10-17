"""Pull a merchant's paystack transactions into the ledger.

The window runs from the merchant's last finished sync (or 30 days back) to the moment
this sync starts. Transactions are upserted on their paystack id and customers on their
email, so a window synced twice (overlapping runs, retries) changes nothing.
last_transaction_sync_at only moves once a sync finishes, so a failed sync is covered
by the next one.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackClient
from app.api.models.customers import Customer
from app.api.models.enums import (
    Currency,
    InitialSyncStatus,
    OnboardingStep,
    TransactionChannel,
    TransactionStatus,
)
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchants import Merchant
from app.api.models.transactions import Transaction
from app.api.services.customers import is_merchant_email

INITIAL_SYNC_DAYS: int = 30
PER_PAGE: int = 100

# paystack channel -> ours; anything unknown is stored as other
CHANNELS: dict[str, TransactionChannel] = {
    **{channel.value: channel for channel in TransactionChannel},
    "dedicated_nuban": TransactionChannel.BANK_TRANSFER,
}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _customer_name(customer: dict) -> str | None:
    name: str = " ".join(
        part.strip() for part in (customer.get("first_name"), customer.get("last_name")) if part
    ).strip()
    return name or None


def _customer_email(customer: dict) -> str | None:
    email: str = (customer.get("email") or "").strip().lower()
    return email or None


class TransactionSync:
    def __init__(self, session: Session, client: PaystackClient, merchant: Merchant):
        self._session = session
        self._client = client
        self._merchant = merchant
        # email -> customer id, so each customer is upserted once per sync
        self._customer_ids: dict[str, UUID] = {}

    def window_start(self, started_at: datetime, initial: bool) -> datetime:
        if initial or not self._merchant.last_transaction_sync_at:
            return started_at - timedelta(days=INITIAL_SYNC_DAYS)
        return self._merchant.last_transaction_sync_at

    def run(self, initial: bool, started_at: datetime | None = None) -> int:
        """Sync every transaction in the window; returns how many were stored"""
        started_at = started_at or datetime.now(UTC)
        from_: datetime = self.window_start(started_at, initial)
        onboarding: MerchantOnboarding | None = self._onboarding() if initial else None

        if onboarding:
            # a retry starts the count again from the first page
            onboarding.initial_sync_status = InitialSyncStatus.IN_PROGRESS
            onboarding.initial_sync_processed = 0
            onboarding.updated_at = started_at
            self._session.commit()

        page: int = 1
        stored: int = 0
        while True:
            body: dict = self._client.list_transactions(
                per_page=PER_PAGE, page=page, from_=from_, to=started_at
            )
            transactions: list[dict] = body.get("data") or []
            meta: dict = body.get("meta") or {}

            if onboarding and page == 1:
                onboarding.initial_sync_total = int(meta.get("total") or len(transactions))

            stored += self._store_page(transactions, started_at)

            if onboarding:
                onboarding.initial_sync_processed += len(transactions)
            # one commit per page: progress shows as it goes, and a failed page keeps
            # what was already stored (the next sync upserts over it)
            self._session.commit()

            if not transactions or page >= int(meta.get("pageCount") or 1):
                break
            page += 1

        self._finish(onboarding, started_at)
        return stored

    def _onboarding(self) -> MerchantOnboarding | None:
        return self._session.scalar(
            select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == self._merchant.id)
        )

    def _finish(self, onboarding: MerchantOnboarding | None, started_at: datetime):
        # an overlapping sync may already have finished a later window
        self._session.execute(
            update(Merchant)
            .where(Merchant.id == self._merchant.id)
            .values(
                last_transaction_sync_at=func.greatest(
                    func.coalesce(Merchant.last_transaction_sync_at, started_at), started_at
                )
            )
        )

        if onboarding:
            onboarding.initial_sync_status = InitialSyncStatus.COMPLETED
            if onboarding.current_step == OnboardingStep.INITIAL_SYNC:
                onboarding.current_step = OnboardingStep.FIRST_RECONCILIATION
            onboarding.updated_at = datetime.now(UTC)

        self._session.commit()

    def _store_page(self, transactions: list[dict], synced_at: datetime) -> int:
        # keyed by paystack id: one upsert can't touch the same row twice
        rows: dict[int, dict[str, Any]] = {}

        for transaction in transactions:
            row: dict[str, Any] | None = self._to_row(transaction, synced_at)
            if row:
                rows[row["paystack_transaction_id"]] = row

        if not rows:
            return 0

        # on the table, so keys are column names (the orm attribute is metadata_, and
        # Transaction.metadata is the declarative MetaData)
        table = Transaction.__table__
        stmt = insert(table).values(list(rows.values()))
        stmt = stmt.on_conflict_do_update(
            constraint="transactions_merchant_paystack_id_uq",
            # reconciliation fields and the linked order belong to the app, not paystack
            set_={
                "status": stmt.excluded.status,
                "channel": stmt.excluded.channel,
                "paid_at": stmt.excluded.paid_at,
                "paystack_fees": stmt.excluded.paystack_fees,
                "customer_email": stmt.excluded.customer_email,
                "customer_name": stmt.excluded.customer_name,
                "customer_id": func.coalesce(table.c.customer_id, stmt.excluded.customer_id),
                "metadata": stmt.excluded["metadata"],
                "synced_at": stmt.excluded.synced_at,
            },
        )
        self._session.execute(stmt)
        return len(rows)

    def _to_row(self, transaction: dict, synced_at: datetime) -> dict[str, Any] | None:
        transaction_id = transaction.get("id")
        if transaction_id is None or not transaction.get("reference"):
            sentry_logger.warning("Skipped paystack transaction without an id or reference")
            return None

        try:
            currency = Currency(transaction.get("currency"))
            status = TransactionStatus(transaction.get("status"))
        except ValueError:
            # a currency or status the ledger can't represent yet; skipped, not guessed
            sentry_logger.warning(
                "Skipped paystack transaction {transaction_id}: currency {currency}, "
                "status {status}",
                transaction_id=str(transaction_id),
                currency=str(transaction.get("currency")),
                status=str(transaction.get("status")),
            )
            return None

        customer: dict = transaction.get("customer") or {}
        metadata = transaction.get("metadata")

        return {
            "merchant_id": self._merchant.id,
            "paystack_transaction_id": transaction_id,
            "paystack_reference": transaction.get("reference"),
            "amount": transaction.get("amount"),
            "currency": currency,
            "channel": CHANNELS.get(transaction.get("channel") or "", TransactionChannel.OTHER),
            "status": status,
            "paid_at": _parse_datetime(transaction.get("paid_at") or transaction.get("paidAt")),
            "paystack_fees": transaction.get("fees"),
            "customer_email": _customer_email(customer),
            "customer_name": _customer_name(customer),
            "customer_id": self._customer_id(customer, transaction),
            # paystack sends an empty string when there is no metadata
            "metadata": metadata if isinstance(metadata, dict) else None,
            "synced_at": synced_at,
        }

    def _customer_id(self, customer: dict, transaction: dict) -> UUID | None:
        email: str | None = _customer_email(customer)
        if not email:
            return None
        if email in self._customer_ids:
            return self._customer_ids[email]

        values: dict[str, Any] = {
            "merchant_id": self._merchant.id,
            "email": email,
            "name": _customer_name(customer),
            "phone": customer.get("phone") or None,
            "paystack_customer_code": customer.get("customer_code") or None,
            "is_shared": is_merchant_email(self._merchant, email),
            "first_seen_at": _parse_datetime(
                transaction.get("created_at") or transaction.get("createdAt")
            ),
        }

        try:
            customer_id: UUID = self._upsert_customer(values)
        except IntegrityError:
            # the CUS code is already on another of the merchant's customers (the payer
            # changed email on paystack); link by email and leave the code where it is
            values["paystack_customer_code"] = None
            customer_id = self._upsert_customer(values)

        self._customer_ids[email] = customer_id
        return customer_id

    def _upsert_customer(self, values: dict[str, Any]) -> UUID:
        stmt = insert(Customer).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="customers_merchant_email_uq",
            # fill gaps only: details the merchant entered are never overwritten
            set_={
                "name": func.coalesce(Customer.name, stmt.excluded.name),
                "phone": func.coalesce(Customer.phone, stmt.excluded.phone),
                "paystack_customer_code": func.coalesce(
                    Customer.paystack_customer_code, stmt.excluded.paystack_customer_code
                ),
                # least() skips nulls, so this is the earliest known payment
                "first_seen_at": func.least(Customer.first_seen_at, stmt.excluded.first_seen_at),
            },
        ).returning(Customer.id)

        with self._session.begin_nested():
            return self._session.execute(stmt).scalar_one()


def mark_initial_sync_failed(session: Session, merchant_id: UUID):
    session.execute(
        update(MerchantOnboarding)
        .where(
            MerchantOnboarding.merchant_id == merchant_id,
            MerchantOnboarding.initial_sync_status == InitialSyncStatus.IN_PROGRESS,
        )
        .values(initial_sync_status=InitialSyncStatus.FAILED, updated_at=datetime.now(UTC))
    )
    session.commit()


def merchants_due_for_sync(session: Session) -> list[UUID]:
    """Connected, active merchants whose initial sync is done; the initial sync itself
    runs from onboarding, not the schedule"""
    return list(
        session.scalars(
            select(Merchant.id)
            .join(MerchantOnboarding, MerchantOnboarding.merchant_id == Merchant.id)
            .where(
                Merchant.is_active.is_(True),
                Merchant.paystack_secret_key.is_not(None),
                MerchantOnboarding.initial_sync_status == InitialSyncStatus.COMPLETED,
            )
        )
    )
