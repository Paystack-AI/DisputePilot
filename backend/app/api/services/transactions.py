from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.customers import Customer
from app.api.models.enums import (
    InitialSyncStatus,
    OrderStatus,
    ReconciliationStatus,
    TransactionStatus,
)
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.matching import MatchingRepository
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.repo.orders import OrderRepository
from app.api.repo.readiness import ReadinessRepository
from app.api.repo.transactions import TransactionRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.customers import CustomerRef
from app.api.schemas.fulfillments import FulfillmentSummary
from app.api.schemas.pagination import PageMeta
from app.api.schemas.readiness import Readiness, ReadinessDetail
from app.api.schemas.transactions import (
    TransactionDetail,
    TransactionDispute,
    TransactionFlag,
    TransactionListQuery,
    TransactionMatch,
    TransactionOrder,
    TransactionOrderRef,
    TransactionResponse,
    TransactionSyncResponse,
)
from app.api.services.readiness import readiness_for
from app.api.services.readiness import summary as readiness_summary
from app.api.services.transaction_sync import enqueue_transaction_sync
from app.core.exceptions import (
    AppException,
    MatchConflictError,
    NotFoundError,
    PaystackNotConnectedError,
    ServerError,
    SyncInProgressError,
)


def _transaction_fields(transaction: Transaction) -> dict[str, Any]:
    return {
        "id": transaction.id,
        "paystack_reference": transaction.paystack_reference,
        "paystack_transaction_id": transaction.paystack_transaction_id,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "channel": transaction.channel,
        "status": transaction.status,
        "paid_at": transaction.paid_at,
        "created_at": transaction.paystack_created_at,
        "paystack_fees": transaction.paystack_fees,
        "customer_email": transaction.customer_email,
        "customer_name": transaction.customer_name,
        "order_id": transaction.order_id,
        "reconciliation_status": transaction.reconciliation_status,
        "reconciled_at": transaction.reconciled_at,
        "flag_reason": transaction.flag_reason,
        "flagged_at": transaction.flagged_at,
        "synced_at": transaction.synced_at,
    }


def transaction_response(
    transaction: Transaction,
    customer: Customer | None,
    order: Order | None,
    readiness: Readiness | None = None,
) -> TransactionResponse:
    return TransactionResponse.model_validate(
        {
            **_transaction_fields(transaction),
            "customer": CustomerRef.model_validate(customer) if customer else None,
            "order": TransactionOrderRef.model_validate(order) if order else None,
            "readiness": readiness,
        }
    )


class TransactionService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_transactions(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        self._transaction_repo = self._uow.repo(TransactionRepository)
        self._order_repo = self._uow.repo(OrderRepository)

    async def _get_transaction(
        self, merchant_id: UUID, reference: str, for_update: bool = False
    ) -> tuple[Transaction, Customer | None, Order | None]:
        # other merchants' payments are reported as missing, so existence is not revealed
        found = await self._transaction_repo.get_by_reference(
            merchant_id, reference, for_update=for_update
        )
        if not found:
            raise NotFoundError("Transaction")
        return found

    async def _save(self, merchant_id: UUID, reference: str, action: str):
        try:
            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while {action} transaction {reference} for merchant {merchant_id}",
                action=action,
                reference=reference,
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

    async def list_transactions(
        self, curr_merchant: Merchant, query: TransactionListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[TransactionResponse], PageMeta]:
        await self._uow_transactions(uow)

        rows, total = await self._transaction_repo.list_transactions(curr_merchant.id, query)
        scores: dict[UUID, ReadinessDetail] = await readiness_for(
            self._uow.repo(ReadinessRepository), [row[0] for row in rows]
        )

        transactions: list[TransactionResponse] = [
            transaction_response(
                transaction, customer, order, readiness_summary(scores.get(transaction.id))
            )
            for transaction, customer, order in rows
        ]
        return transactions, PageMeta.build(query, total)

    async def get_transaction(
        self, curr_merchant: Merchant, reference: str, uow: UnitOfWorkRepository
    ) -> TransactionDetail:
        await self._uow_transactions(uow)

        transaction, customer, order = await self._get_transaction(curr_merchant.id, reference)

        # separate queries: joining one-to-many tables would multiply the rows
        fulfillments = await self._transaction_repo.list_fulfillments(transaction)
        dispute = await self._transaction_repo.latest_dispute(transaction)

        return TransactionDetail.model_validate(
            {
                **_transaction_fields(transaction),
                "customer": CustomerRef.model_validate(customer) if customer else None,
                "order": TransactionOrder.model_validate(order) if order else None,
                "metadata": transaction.metadata_,
                "fulfillments": [FulfillmentSummary.model_validate(f) for f in fulfillments],
                "dispute": TransactionDispute.model_validate(dispute) if dispute else None,
                "readiness": (
                    await readiness_for(self._uow.repo(ReadinessRepository), [transaction])
                ).get(transaction.id),
            }
        )

    async def match_transaction(
        self,
        curr_merchant: Merchant,
        reference: str,
        payload: TransactionMatch,
        uow: UnitOfWorkRepository,
    ) -> TransactionResponse:
        """Link the payment to one of the merchant's orders by hand"""
        await self._uow_transactions(uow)
        merchant_id: UUID = curr_merchant.id

        try:
            transaction, customer, _ = await self._get_transaction(
                merchant_id, reference, for_update=True
            )

            found = await self._order_repo.get_with_customer(
                merchant_id, payload.order_id, for_update=True
            )
            if not found:
                raise NotFoundError("Order")
            order, order_customer, _ = found

            if transaction.order_id == order.id:
                # already matched to this order: nothing to change
                return transaction_response(transaction, customer or order_customer, order)

            if transaction.order_id:
                raise MatchConflictError("already_matched_to_another_order")
            if transaction.status != TransactionStatus.SUCCESS:
                raise MatchConflictError("transaction_not_successful")
            if order.status == OrderStatus.CANCELLED:
                raise MatchConflictError("order_cancelled")
            if order.currency != transaction.currency:
                raise MatchConflictError("currency_mismatch")

            now: datetime = datetime.now(UTC)

            transaction.order_id = order.id
            transaction.reconciliation_status = ReconciliationStatus.MANUALLY_MATCHED
            transaction.reconciled_at = now
            # a match settles the review the flag asked for
            transaction.flag_reason = None
            transaction.flagged_at = None
            if not transaction.customer_id:
                transaction.customer_id = order.customer_id

            # the matched payment pays the order
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.PAID
                order.updated_at = now
        except AppException:
            await self._uow.rollback()
            raise

        await self._uow.repo(MatchingRepository).drop_stale_suggestions(merchant_id)
        await self._save(merchant_id, reference, "matching")

        sentry_logger.info(
            "Merchant {merchant_id} matched transaction {reference} to order {order_id}",
            merchant_id=str(merchant_id),
            reference=reference,
            order_id=str(order.id),
        )

        return await self._scored_response(transaction, customer or order_customer, order)

    async def _scored_response(
        self, transaction: Transaction, customer: Customer | None, order: Order | None
    ) -> TransactionResponse:
        scores: dict[UUID, ReadinessDetail] = await readiness_for(
            self._uow.repo(ReadinessRepository), [transaction]
        )
        return transaction_response(
            transaction, customer, order, readiness_summary(scores.get(transaction.id))
        )

    async def flag_transaction(
        self,
        curr_merchant: Merchant,
        reference: str,
        payload: TransactionFlag,
        uow: UnitOfWorkRepository,
    ) -> TransactionResponse:
        """Mark the payment for review; flagging again only updates the reason"""
        await self._uow_transactions(uow)
        merchant_id: UUID = curr_merchant.id

        transaction, customer, order = await self._get_transaction(
            merchant_id, reference, for_update=True
        )

        if transaction.reconciliation_status != ReconciliationStatus.FLAGGED:
            transaction.flagged_at = datetime.now(UTC)
        transaction.reconciliation_status = ReconciliationStatus.FLAGGED
        transaction.flag_reason = payload.reason

        await self._uow.repo(MatchingRepository).drop_stale_suggestions(merchant_id)
        await self._save(merchant_id, reference, "flagging")

        sentry_logger.info(
            "Merchant {merchant_id} flagged transaction {reference}",
            merchant_id=str(merchant_id),
            reference=reference,
        )

        return transaction_response(transaction, customer, order)

    async def unflag_transaction(
        self, curr_merchant: Merchant, reference: str, uow: UnitOfWorkRepository
    ) -> TransactionResponse:
        """Clear the flag: back to manually matched when linked to an order (the merchant
        has now reviewed it), unmatched otherwise. A payment that isn't flagged is
        returned as it is"""
        await self._uow_transactions(uow)
        merchant_id: UUID = curr_merchant.id

        transaction, customer, order = await self._get_transaction(
            merchant_id, reference, for_update=True
        )

        if transaction.reconciliation_status != ReconciliationStatus.FLAGGED:
            return transaction_response(transaction, customer, order)

        transaction.reconciliation_status = (
            ReconciliationStatus.MANUALLY_MATCHED
            if transaction.order_id
            else ReconciliationStatus.UNMATCHED
        )
        transaction.flag_reason = None
        transaction.flagged_at = None

        await self._save(merchant_id, reference, "unflagging")

        sentry_logger.info(
            "Merchant {merchant_id} unflagged transaction {reference}",
            merchant_id=str(merchant_id),
            reference=reference,
        )

        return await self._scored_response(transaction, customer, order)

    async def sync_transactions(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> TransactionSyncResponse:
        """Queue a sync from the merchant's last finished sync"""
        await self._setup_uow(uow)

        if not curr_merchant.paystack_secret_key:
            raise PaystackNotConnectedError()

        onboarding: MerchantOnboarding | None = await self._uow.repo(
            MerchantOnboardingRepository
        ).get_record(merchant_id=curr_merchant.id)

        # the initial sync already covers the window and drives the onboarding progress
        if onboarding and onboarding.initial_sync_status == InitialSyncStatus.IN_PROGRESS:
            raise SyncInProgressError()

        await enqueue_transaction_sync(curr_merchant.id, initial=False)

        sentry_logger.info(
            "Merchant {merchant_id} requested a transaction sync",
            merchant_id=str(curr_merchant.id),
        )

        return TransactionSyncResponse(last_sync_at=curr_merchant.last_transaction_sync_at)
