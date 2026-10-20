from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.enums import DisputeStatus, InitialSyncStatus
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.models.transactions import Transaction

RESOLVED_STATUSES: tuple[DisputeStatus, ...] = (
    DisputeStatus.WON,
    DisputeStatus.LOST,
    DisputeStatus.AUTO_ACCEPTED,
)
# the merchant still has to respond (submitted ones are with the bank)
AWAITING_STATUSES: tuple[DisputeStatus, ...] = (
    DisputeStatus.PENDING,
    DisputeStatus.EVIDENCE_GENERATED,
)


class SyncDisputeRepository:
    """Dispute intake for the worker (webhooks, and later the poller)"""

    def __init__(self, session: Session):
        self._session = session

    def transaction_id(self, merchant_id: UUID, paystack_transaction_id: int) -> UUID | None:
        return self._session.scalar(
            select(Transaction.id).where(
                Transaction.merchant_id == merchant_id,
                Transaction.paystack_transaction_id == paystack_transaction_id,
            )
        )

    def get_for_update(self, merchant_id: UUID, paystack_dispute_id: int) -> Dispute | None:
        return self._session.scalar(
            select(Dispute)
            .where(
                Dispute.merchant_id == merchant_id,
                Dispute.paystack_dispute_id == paystack_dispute_id,
            )
            .with_for_update()
        )

    def insert_if_missing(self, values: dict[str, Any]) -> bool:
        """Inserts the dispute unless a concurrent intake already did; True when inserted"""
        result = self._session.execute(
            insert(Dispute)
            .values(**values)
            .on_conflict_do_nothing(constraint="disputes_merchant_paystack_id_uq")
            .returning(Dispute.id)
        )
        return result.scalar() is not None

    def settings(self, merchant_id: UUID) -> MerchantSettings | None:
        return self._session.scalar(
            select(MerchantSettings).where(MerchantSettings.merchant_id == merchant_id)
        )

    def add_notification(self, notification: NotificationLog) -> NotificationLog:
        self._session.add(notification)
        self._session.flush()
        return notification

    # ------------------------------ poller ------------------------------ #

    def merchants_to_poll(self, webhook_quiet_since: datetime) -> list[UUID]:
        """Connected, active merchants past onboarding whose webhook has not delivered
        since webhook_quiet_since (or was never set up)"""
        return list(
            self._session.scalars(
                select(Merchant.id)
                .join(MerchantOnboarding, MerchantOnboarding.merchant_id == Merchant.id)
                .where(
                    Merchant.is_active.is_(True),
                    Merchant.paystack_secret_key.is_not(None),
                    MerchantOnboarding.initial_sync_status == InitialSyncStatus.COMPLETED,
                    or_(
                        Merchant.webhook_last_received_at.is_(None),
                        Merchant.webhook_last_received_at < webhook_quiet_since,
                    ),
                )
            )
        )

    def open_paystack_ids(self, merchant_id: UUID) -> list[int]:
        """Disputes paystack has not resolved yet, to fetch one by one"""
        return list(
            self._session.scalars(
                select(Dispute.paystack_dispute_id).where(
                    Dispute.merchant_id == merchant_id,
                    Dispute.status.not_in(RESOLVED_STATUSES),
                    or_(Dispute.paystack_status.is_(None), Dispute.paystack_status != "resolved"),
                )
            )
        )

    # ------------------------------ deadline watcher ------------------------------ #

    def awaiting_response(self, now: datetime, until: datetime) -> list[tuple[Dispute, Merchant]]:
        """Disputes still waiting on the merchant whose deadline falls in [now, until],
        locked and skipping ones another watcher run holds"""
        rows = self._session.execute(
            select(Dispute, Merchant)
            .join(Merchant, Merchant.id == Dispute.merchant_id)
            .where(
                Dispute.status.in_(AWAITING_STATUSES),
                Dispute.due_at >= now,
                Dispute.due_at <= until,
                Merchant.is_active.is_(True),
            )
            .order_by(Dispute.due_at)
            .with_for_update(of=Dispute, skip_locked=True)
        )
        return [(row[0], row[1]) for row in rows.all()]
