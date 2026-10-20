from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased, load_only

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeStatus,
    EvidenceState,
    InitialSyncStatus,
    TransactionChannel,
    TransactionStatus,
)
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.files import StoredFile
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository
from app.api.schemas.disputes import DisputeListQuery

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

    # ------------------------------ submission ------------------------------ #

    def get_by_id_for_update(self, dispute_id: UUID) -> Dispute | None:
        return self._session.get(Dispute, dispute_id, with_for_update=True)

    def merchant(self, merchant_id: UUID) -> Merchant | None:
        return self._session.get(Merchant, merchant_id)

    def transaction_reference(self, transaction_id: UUID) -> str | None:
        return self._session.scalar(
            select(Transaction.paystack_reference).where(Transaction.id == transaction_id)
        )

    def submitted_snapshot(self, dispute_id: UUID) -> dict | None:
        """The document as approved by the merchant (the latest submitted revision)"""
        return self._session.scalar(
            select(EvidenceRevision.snapshot)
            .where(
                EvidenceRevision.dispute_id == dispute_id,
                EvidenceRevision.snapshot.is_not(None),
            )
            .order_by(EvidenceRevision.version.desc())
            .limit(1)
        )


@dataclass
class DisputeLinks:
    """A dispute with what its evidence is built from"""

    dispute: Dispute
    transaction: Transaction
    customer: Customer | None
    order: Order | None
    # payment_count, first_payment_at, dispute_count; None for no or a shared customer
    history: dict | None


# the dispute columns a list row needs (the narrative, strategy, quality json etc. are not)
SUMMARY_COLUMNS: tuple = (
    Dispute.id,
    Dispute.paystack_dispute_id,
    Dispute.status,
    Dispute.paystack_status,
    Dispute.category,
    Dispute.reason_raw,
    Dispute.amount,
    Dispute.currency,
    Dispute.created_at,
    Dispute.due_at,
    Dispute.evidence_quality_score,
    Dispute.evidence_quality,
    Dispute.evidence_suggestions,
    Dispute.evidence_state,
    Dispute.submission_state,
)


# hours left for each urgency band (critical under 4, warning 4 to 8, safe over 8)
CRITICAL_HOURS: int = 4
WARNING_HOURS: int = 8


class DisputeRepository(BaseRepository[BaseModel, Dispute]):
    model = Dispute

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return Dispute(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])

        return filter_conditions

    # ------------------------------ links ------------------------------ #

    @staticmethod
    def _history_columns() -> list:
        """The customer's history for the evidence, as subqueries on the joined customer:
        successful payments, the first one, and disputes raised (null without a customer)"""
        payment = aliased(Transaction)
        disputed = aliased(Transaction)
        other = aliased(Dispute)
        success = payment.status == TransactionStatus.SUCCESS
        return [
            select(func.count(payment.id))
            .where(payment.customer_id == Customer.id, success)
            .scalar_subquery()
            .label("payment_count"),
            select(func.min(payment.paid_at))
            .where(payment.customer_id == Customer.id, success)
            .scalar_subquery()
            .label("first_payment_at"),
            select(func.count(other.id))
            .join(disputed, disputed.id == other.transaction_id)
            .where(disputed.customer_id == Customer.id)
            .scalar_subquery()
            .label("dispute_count"),
        ]

    @staticmethod
    def _joined(stmt: Select) -> Select:
        """The payment's order and customer (from the sync, else the order's)"""
        return stmt.outerjoin(Order, Order.id == Transaction.order_id).outerjoin(
            Customer, Customer.id == func.coalesce(Transaction.customer_id, Order.customer_id)
        )

    @staticmethod
    def _to_links(dispute: Dispute, row) -> DisputeLinks:
        customer: Customer | None = row.Customer
        history: dict | None = None
        # history only counts for the customer's own email, never a shared one
        if customer and not customer.is_shared:
            history = {
                "payment_count": row.payment_count,
                "first_payment_at": row.first_payment_at,
                "dispute_count": row.dispute_count,
            }
        return DisputeLinks(dispute, row.Transaction, customer, row.Order, history)

    async def get_with_links(
        self, merchant_id: UUID, dispute_id: UUID, for_update: bool = False
    ) -> DisputeLinks | None:
        """The dispute with everything its evidence needs, in one query. for_update locks
        only the dispute row"""
        stmt = self._joined(
            select(Dispute, Transaction, Customer, Order, *self._history_columns()).join(
                Transaction, Transaction.id == Dispute.transaction_id
            )
        ).where(Dispute.id == dispute_id, Dispute.merchant_id == merchant_id)
        if for_update:
            stmt = stmt.with_for_update(of=Dispute)
        row = (await self._async_session.execute(stmt)).one_or_none()
        return self._to_links(row.Dispute, row) if row else None

    async def links_of(self, dispute: Dispute) -> DisputeLinks:
        """get_with_links for a dispute already loaded (and locked): the rest only"""
        row = (
            await self._async_session.execute(
                self._joined(select(Transaction, Customer, Order, *self._history_columns())).where(
                    Transaction.id == dispute.transaction_id
                )
            )
        ).one()
        return self._to_links(dispute, row)

    async def get_for_merchant(
        self, merchant_id: UUID, dispute_id: UUID, for_update: bool = False
    ) -> Dispute | None:
        """The dispute row alone, for actions that need nothing linked"""
        return await self.get_record(for_update=for_update, id=dispute_id, merchant_id=merchant_id)

    async def transaction_channel(self, transaction_id: UUID) -> TransactionChannel | None:
        return await self._async_session.scalar(
            select(Transaction.channel).where(Transaction.id == transaction_id)
        )

    # ------------------------------ list ------------------------------ #

    @staticmethod
    def _urgency_condition(urgency: str, now: datetime):
        awaiting = Dispute.status.in_(AWAITING_STATUSES)
        critical = now + timedelta(hours=CRITICAL_HOURS)
        warning = now + timedelta(hours=WARNING_HOURS)
        if urgency == "critical":
            return and_(awaiting, Dispute.due_at < critical)
        if urgency == "warning":
            return and_(awaiting, Dispute.due_at >= critical, Dispute.due_at < warning)
        return and_(awaiting, Dispute.due_at >= warning)

    async def list_disputes(
        self, merchant_id: UUID, query: DisputeListQuery, now: datetime
    ) -> tuple[list, int]:
        """A page of disputes with only the columns the list shows: each row has the
        dispute (summary fields loaded), the payment's reference, id, order id and
        reconciliation status (for readiness), and the customer's name and email"""
        conditions: list[Any] = [Dispute.merchant_id == merchant_id]
        if query.status:
            conditions.append(Dispute.status.in_(query.status))
        if query.category:
            conditions.append(Dispute.category.in_(query.category))
        if query.urgency:
            conditions.append(
                or_(*(self._urgency_condition(urgency, now) for urgency in query.urgency))
            )

        column = Dispute.due_at if query.sort.lstrip("-") == "due_at" else Dispute.created_at
        order_by = (
            (column.desc(), Dispute.id.desc())
            if query.sort.startswith("-")
            else (column.asc(), Dispute.id.asc())
        )

        stmt: Select = (
            self._joined(
                select(
                    Dispute,
                    Transaction.id.label("transaction_id"),
                    Transaction.paystack_reference,
                    Transaction.order_id,
                    Transaction.reconciliation_status,
                    func.coalesce(Transaction.customer_name, Customer.name).label("customer_name"),
                    func.coalesce(Transaction.customer_email, Customer.email).label(
                        "customer_email"
                    ),
                ).join(Transaction, Transaction.id == Dispute.transaction_id)
            )
            .options(load_only(*SUMMARY_COLUMNS))
            .where(*conditions)
            .order_by(*order_by)
        )

        rows, total = await self._paginate(
            stmt, select(func.count(Dispute.id)).where(*conditions), query.page, query.limit
        )
        return rows, total

    async def fulfillments(self, transaction: Transaction) -> list[Fulfillment]:
        """Recorded against the payment or its order, newest first"""
        linked = [Fulfillment.transaction_id == transaction.id]
        if transaction.order_id:
            linked.append(Fulfillment.order_id == transaction.order_id)
        rows = await self._async_session.scalars(
            select(Fulfillment)
            .where(Fulfillment.merchant_id == transaction.merchant_id, or_(*linked))
            .order_by(Fulfillment.delivery_date.desc(), Fulfillment.id.desc())
        )
        return list(rows)

    async def files_for(
        self, dispute_id: UUID, fulfillment_ids: list[UUID]
    ) -> tuple[list[StoredFile], list[StoredFile]]:
        """The dispute's own documents and the fulfillments' photos, oldest first"""
        conditions = [StoredFile.dispute_id == dispute_id]
        if fulfillment_ids:
            conditions.append(StoredFile.fulfillment_id.in_(fulfillment_ids))
        rows = list(
            await self._async_session.scalars(
                select(StoredFile)
                .where(or_(*conditions))
                .order_by(StoredFile.created_at, StoredFile.id)
            )
        )
        return (
            [f for f in rows if f.dispute_id == dispute_id],
            [f for f in rows if f.dispute_id != dispute_id],
        )

    async def documents_for_update(self, dispute_id: UUID) -> list[StoredFile]:
        return list(
            await self._async_session.scalars(
                select(StoredFile).where(StoredFile.dispute_id == dispute_id).with_for_update()
            )
        )

    async def duplicate_charges(self, transaction: Transaction) -> int:
        """Other successful payments from the same customer for the same amount within a
        day of this one: a real duplicate means an admin_error claim is right"""
        if not transaction.customer_id or not transaction.paid_at:
            return 0
        return await self._async_session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.merchant_id == transaction.merchant_id,
                Transaction.customer_id == transaction.customer_id,
                Transaction.amount == transaction.amount,
                Transaction.status == TransactionStatus.SUCCESS,
                Transaction.id != transaction.id,
                Transaction.paid_at >= transaction.paid_at - timedelta(hours=24),
                Transaction.paid_at <= transaction.paid_at + timedelta(hours=24),
            )
        )

    def add_revision(self, revision: EvidenceRevision) -> EvidenceRevision:
        self._async_session.add(revision)
        return revision

    async def stats(self, merchant_id: UUID) -> dict[str, Any]:
        responded = Dispute.submitted_at.is_not(None)
        row = (
            await self._async_session.execute(
                select(
                    func.count(),
                    func.count().filter(Dispute.status.in_(AWAITING_STATUSES)),
                    func.count().filter(Dispute.status == DisputeStatus.SUBMITTED),
                    func.count().filter(Dispute.status == DisputeStatus.WON),
                    func.count().filter(Dispute.status == DisputeStatus.LOST),
                    func.count().filter(Dispute.status == DisputeStatus.AUTO_ACCEPTED),
                    func.count().filter(
                        responded, Dispute.status.in_([DisputeStatus.WON, DisputeStatus.LOST])
                    ),
                    func.avg(
                        func.extract("epoch", Dispute.submitted_at - Dispute.created_at) / 3600
                    ).filter(responded),
                ).where(Dispute.merchant_id == merchant_id)
            )
        ).one()
        return {
            "total": row[0],
            "open": row[1],
            "submitted": row[2],
            "won": row[3],
            "lost": row[4],
            "auto_accepted": row[5],
            "decided_after_response": row[6],
            "avg_response_hours": float(row[7]) if row[7] is not None else None,
        }

    async def stale_generating(self, started_before: datetime, limit: int = 20) -> list[Dispute]:
        """Chains whose current step has been quiet too long, locked; ones another sweep
        holds are skipped"""
        return list(
            await self._async_session.scalars(
                select(Dispute)
                .where(
                    Dispute.evidence_state == EvidenceState.GENERATING,
                    Dispute.evidence_step_started_at < started_before,
                )
                .order_by(Dispute.evidence_step_started_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def get_by_id_for_update(self, dispute_id: UUID) -> Dispute | None:
        return await self._async_session.get(Dispute, dispute_id, with_for_update=True)
