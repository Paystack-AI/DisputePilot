"""Dispute intake from paystack: creates or updates our record from a paystack dispute
object (a webhook today, the poller next) and links it to its payment. Card details (bin,
last4) are never stored.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackClient
from app.api.models.disputes import Dispute
from app.api.models.enums import Currency, DisputeStatus
from app.api.models.merchants import Merchant
from app.api.repo.disputes import SyncDisputeRepository
from app.worker.services.transaction_sync import TransactionSync, _parse_datetime

# paystack's resolution values (the webhook docs add auto-accepted to the api's two)
DECLINED: str = "declined"  # the merchant's evidence stood: no refund
MERCHANT_ACCEPTED: str = "merchant-accepted"  # the merchant conceded: refunded
AUTO_ACCEPTED: str = "auto-accepted"  # nobody responded before dueAt: refunded
RESOLVED: str = "resolved"
# paystack gives the merchant about 16 hours when dueAt is missing
DEFAULT_RESPONSE_HOURS: int = 16


class DisputeTransactionMissing(Exception):
    """The disputed payment is neither stored nor fetchable from paystack"""


@dataclass(frozen=True)
class DisputeIntake:
    dispute: Dispute
    created: bool
    # it moved to won, lost or auto_accepted in this intake
    resolved_now: bool
    # new, or its status or paystack's status moved: worth a live update
    changed: bool
    reference: str


def _outcome(data: dict) -> DisputeStatus | None:
    """won, lost or auto_accepted for a resolved dispute; None while it is open"""
    resolution: str | None = data.get("resolution")
    if data.get("status") != RESOLVED and not resolution:
        return None
    if resolution == DECLINED:
        return DisputeStatus.WON
    if resolution == AUTO_ACCEPTED:
        return DisputeStatus.AUTO_ACCEPTED
    # merchant-accepted, or a resolution paystack has not documented
    return DisputeStatus.LOST


def _reason(data: dict) -> str | None:
    """The bank's reason: messages[0].body (paystack's messages are {sender, body,
    createdAt}), else the note"""
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in messages:
            body = message.get("body") if isinstance(message, dict) else None
            if isinstance(body, str) and body.strip():
                return body.strip()
    if isinstance(data.get("note"), str) and data["note"].strip():
        return data["note"].strip()
    return None


def _with_customer(transaction: dict, data: dict) -> dict:
    """The dispute's embedded transaction carries an almost empty customer (only
    international_format_phone); the dispute's own customer has the email and name"""
    customer = data.get("customer")
    embedded_customer = transaction.get("customer")
    if not isinstance(customer, dict) or (
        isinstance(embedded_customer, dict) and embedded_customer.get("email")
    ):
        return transaction
    return {**transaction, "customer": customer}


class DisputeIntakeService:
    def __init__(self, session: Session, merchant: Merchant, client: PaystackClient | None):
        self._session = session
        self._merchant = merchant
        self._client = client
        self._repo = SyncDisputeRepository(session)

    def _transaction_id(self, data: dict) -> tuple[UUID, str]:
        """Our payment for the dispute: stored, else taken from the dispute's own copy,
        else fetched from paystack"""
        embedded = data.get("transaction")
        embedded = embedded if isinstance(embedded, dict) else {}
        paystack_id = embedded.get("id") or data.get("transaction_id")
        if paystack_id is None:
            raise DisputeTransactionMissing("dispute without a transaction id")
        paystack_id = int(paystack_id)

        transaction_id: UUID | None = self._repo.transaction_id(self._merchant.id, paystack_id)
        if transaction_id:
            return transaction_id, embedded.get("reference") or data.get(
                "transaction_reference", ""
            )

        sync = TransactionSync(self._session, self._client, self._merchant)
        if embedded.get("reference") and embedded.get("status"):
            sync.store([_with_customer(embedded, data)])
            transaction_id = self._repo.transaction_id(self._merchant.id, paystack_id)

        if not transaction_id and self._client:
            body: dict = self._client.fetch_transaction(paystack_id)
            fetched = body.get("data")
            if isinstance(fetched, dict):
                sync.store([_with_customer(fetched, data)])
                transaction_id = self._repo.transaction_id(self._merchant.id, paystack_id)
                embedded = fetched

        if not transaction_id:
            raise DisputeTransactionMissing(f"transaction {paystack_id} not found")

        sentry_logger.info(
            "Stored transaction {paystack_id} for a dispute of merchant {merchant_id}",
            paystack_id=str(paystack_id),
            merchant_id=str(self._merchant.id),
        )
        return transaction_id, embedded.get("reference") or ""

    def upsert(self, data: dict) -> DisputeIntake:
        """Create or update the dispute from paystack's dispute object. The caller commits"""
        paystack_dispute_id = int(data["id"])
        now: datetime = datetime.now(UTC)
        transaction_id, reference = self._transaction_id(data)
        embedded: dict = (
            data.get("transaction") if isinstance(data.get("transaction"), dict) else {}
        )

        try:
            currency = Currency(data.get("currency") or embedded.get("currency") or "NGN")
        except ValueError:
            currency = Currency.NGN
        due_at: datetime | None = _parse_datetime(data.get("dueAt") or data.get("due_at"))
        # only what paystack sent: a partial event never clears or moves stored values
        paystack_fields: dict[str, Any] = {
            key: value
            for key, value in {
                "paystack_status": data.get("status"),
                "paystack_resolution": data.get("resolution"),
                "paystack_category": data.get("category"),
                "resolved_at": _parse_datetime(data.get("resolvedAt") or data.get("resolved_at")),
                "due_at": due_at,
            }.items()
            if value is not None
        }
        paystack_fields["paystack_synced_at"] = now
        reason: str | None = _reason(data)
        amount = data.get("refund_amount") or embedded.get("amount") or 0

        created: bool = self._repo.insert_if_missing(
            {
                "merchant_id": self._merchant.id,
                "transaction_id": transaction_id,
                "paystack_dispute_id": paystack_dispute_id,
                "paystack_reference": reference or data.get("transaction_reference") or "",
                "amount": int(amount),
                "currency": currency,
                "reason_raw": reason,
                "status": DisputeStatus.PENDING,
                "created_at": _parse_datetime(data.get("createdAt") or data.get("created_at"))
                or now,
                **paystack_fields,
                "due_at": due_at or now + timedelta(hours=DEFAULT_RESPONSE_HOURS),
            }
        )

        # locked so a webhook and the poller can't update it at the same time
        dispute: Dispute = self._repo.get_for_update(self._merchant.id, paystack_dispute_id)
        before: tuple = (dispute.status, dispute.paystack_status)
        for field, value in paystack_fields.items():
            setattr(dispute, field, value)
        if reason and not dispute.reason_raw:
            dispute.reason_raw = reason

        resolved_now: bool = False
        outcome: DisputeStatus | None = _outcome(data)
        if outcome and dispute.status != outcome:
            dispute.status = outcome
            dispute.resolution = outcome.value
            resolved_now = True

        return DisputeIntake(
            dispute=dispute,
            created=created,
            resolved_now=resolved_now,
            changed=created or before != (dispute.status, dispute.paystack_status),
            reference=dispute.paystack_reference,
        )
