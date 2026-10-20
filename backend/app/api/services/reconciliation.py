"""Merchant-triggered reconciliation sessions.

A session covers a range of days in the merchant's timezone. Starting one runs the
matching tiers over that range (the automatic pass after each sync has usually done most
of it); the merchant then accepts or rejects suggestions and resolves what is left, and
completing it saves the counts and emails the summary. One session is open at a time.
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError

from app.api.models.customers import Customer
from app.api.models.enums import (
    MatchSuggestionStatus,
    OnboardingStep,
    OrderStatus,
    ReconciliationSessionStatus,
    ReconciliationStatus,
)
from app.api.models.match_suggestions import MatchSuggestion
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.reconciliation_sessions import ReconciliationSession
from app.api.models.transactions import Transaction
from app.api.repo.matching import MatchingRepository
from app.api.repo.merchant_onboarding import MerchantOnboardingRepository
from app.api.repo.merchant_settings import MerchantSettingsRepository
from app.api.repo.readiness import ReadinessRepository
from app.api.repo.reconciliation import ReconciliationRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.pagination import PageMeta, PageParams
from app.api.schemas.readiness import ReadinessDetail
from app.api.schemas.reconciliation import (
    FlaggedOrder,
    FlaggedPayment,
    MatchDecision,
    MatchDecisionResponse,
    MatchedItem,
    ReconciliationSessionResponse,
    ReconciliationStart,
    ReconciliationSummary,
    ReconciliationTotals,
    ReconciliationView,
    SuggestionItem,
)
from app.api.services.events import publish_event
from app.api.services.notifications import NotificationService
from app.api.services.order_management import order_response
from app.api.services.readiness import readiness_for
from app.api.services.readiness import summary as readiness_summary
from app.api.services.reconciliation_engine import run_matching
from app.api.services.transactions import transaction_response
from app.core.exceptions import AppException, MatchConflictError, NotFoundError, ServerError

# needs_review in the summary looks this far back
REVIEW_DAYS: int = 30
# suggestions at or above this are shown as likely, below as possible
LIKELY_CONFIDENCE: int = 90


def _day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


class ReconciliationService:
    def __init__(self, redis: Redis, notification_service: NotificationService | None = None):
        self._redis = redis
        self._notification_service = notification_service or NotificationService()
        self._uow: UnitOfWorkRepository | None = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow
        self._repo = uow.repo(ReconciliationRepository)
        self._matching = uow.repo(MatchingRepository)
        self._readiness = uow.repo(ReadinessRepository)

    async def _settings(self, merchant_id: UUID) -> MerchantSettings | None:
        return await self._uow.repo(MerchantSettingsRepository).get_record(merchant_id=merchant_id)

    @staticmethod
    def _zone(settings: MerchantSettings | None) -> ZoneInfo:
        try:
            return ZoneInfo(settings.timezone if settings and settings.timezone else "UTC")
        except (KeyError, ValueError):
            return ZoneInfo("UTC")

    @staticmethod
    def _bounds(session: ReconciliationSession, zone: ZoneInfo) -> tuple[datetime, datetime]:
        """[start of the first day, start of the day after the last) in the merchant's zone"""
        return (
            _day_start(session.date_range_start, zone),
            _day_start(session.date_range_end + timedelta(days=1), zone),
        )

    async def _commit(self, merchant_id: UUID, action: str):
        try:
            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while {action} for merchant {merchant_id}",
                action=action,
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

    async def _publish(self, merchant_id: UUID, data: dict):
        """Live update for the merchant's open dashboards; best effort"""
        try:
            await publish_event(self._redis, merchant_id, "reconciliation.updated", data)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Reconciliation event could not be published for merchant {merchant_id}",
                merchant_id=str(merchant_id),
            )

    # ------------------------------ responses ------------------------------ #

    async def _totals(self, session: ReconciliationSession, zone: ZoneInfo) -> ReconciliationTotals:
        if session.status == ReconciliationSessionStatus.COMPLETED:
            # the counts saved when it was completed (suggested ones were unmatched then)
            return ReconciliationTotals(
                total_transactions=session.total_transactions,
                matched=session.matched_count,
                suggested=0,
                unmatched_payments=session.unmatched_payments_count,
                unmatched_orders=session.unmatched_orders_count,
                flagged=session.flagged_count,
            )
        paid_from, paid_to = self._bounds(session, zone)
        return ReconciliationTotals(
            **await self._repo.totals(session.merchant_id, paid_from, paid_to)
        )

    async def _session_response(
        self, session: ReconciliationSession, zone: ZoneInfo
    ) -> ReconciliationSessionResponse:
        return ReconciliationSessionResponse(
            id=session.id,
            date_range_start=session.date_range_start,
            date_range_end=session.date_range_end,
            status=session.status,
            totals=await self._totals(session, zone),
            completed_at=session.completed_at,
            created_at=session.created_at,
        )

    async def _view(self, session: ReconciliationSession, zone: ZoneInfo) -> ReconciliationView:
        merchant_id: UUID = session.merchant_id
        start, end = self._bounds(session, zone)

        matched_rows = await self._repo.matched(merchant_id, start, end)
        scores: dict[UUID, ReadinessDetail] = await readiness_for(
            self._readiness, [row[0] for row in matched_rows]
        )
        matched = [
            MatchedItem(
                transaction=transaction_response(
                    transaction, customer, order, readiness_summary(scores.get(transaction.id))
                ),
                order=order_response(order, order_customer, True),
                tier=transaction.match_tier,
                confidence=transaction.match_confidence,
                accepted_at=transaction.reconciled_at,
            )
            for transaction, customer, order, order_customer in matched_rows
        ]
        suggestions = [
            SuggestionItem(
                id=suggestion.id,
                transaction=transaction_response(transaction, customer, None),
                order=order_response(order, order_customer, False),
                tier=suggestion.tier,
                likelihood_percent=suggestion.confidence,
                confidence_tier=(
                    "likely" if suggestion.confidence >= LIKELY_CONFIDENCE else "possible"
                ),
                reasoning=suggestion.reason,
            )
            for suggestion, transaction, customer, order, order_customer in (
                await self._repo.suggestions(merchant_id, start, end)
            )
        ]

        return ReconciliationView(
            session=await self._session_response(session, zone),
            matched=matched,
            suggestions=suggestions,
            unmatched_payments=[
                transaction_response(*row)
                for row in await self._repo.unmatched_payments(merchant_id, start, end)
            ],
            unmatched_orders=[
                order_response(*row)
                for row in await self._repo.unmatched_orders(merchant_id, start, end)
            ],
            flagged=[
                FlaggedPayment(
                    transaction=transaction_response(transaction, customer, order),
                    reason=transaction.flag_reason,
                )
                for transaction, customer, order in await self._repo.flagged(
                    merchant_id, start, end
                )
            ],
            flagged_orders=[
                FlaggedOrder(
                    order=order_response(order, customer, linked), reason=order.flag_reason
                )
                for order, customer, linked in await self._repo.flagged_orders(
                    merchant_id, start, end
                )
            ],
        )

    async def _open_totals(self, merchant_id: UUID) -> ReconciliationTotals | None:
        session: ReconciliationSession | None = await self._repo.get_open(merchant_id)
        if not session:
            return None
        return await self._totals(session, self._zone(await self._settings(merchant_id)))

    # ------------------------------ sessions ------------------------------ #

    async def start(
        self, curr_merchant: Merchant, payload: ReconciliationStart, uow: UnitOfWorkRepository
    ) -> tuple[ReconciliationView, bool]:
        """Open a session (or continue the open one) and match its range. Returns the view
        and whether a session was created"""
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        settings: MerchantSettings | None = await self._settings(merchant_id)
        zone: ZoneInfo = self._zone(settings)

        session: ReconciliationSession | None = await self._repo.get_open(merchant_id)
        created: bool = session is None
        if created:
            today: date = datetime.now(zone).date()
            if payload.date_range_start and payload.date_range_end:
                start, end = payload.date_range_start, payload.date_range_end
            else:
                days: int = max(settings.default_reconciliation_range if settings else 1, 1)
                start, end = today - timedelta(days=days - 1), today

            session = ReconciliationSession(
                merchant_id=merchant_id,
                date_range_start=start,
                date_range_end=end,
                status=ReconciliationSessionStatus.IN_PROGRESS,
                created_at=datetime.now(UTC),
            )
            try:
                self._repo.add(model=session)
                await uow.flush()
            except IntegrityError:
                # opened by a concurrent request: continue that one
                await uow.rollback()
                session = await self._repo.get_open(merchant_id)
                created = False
                if not session:
                    raise ServerError() from None

        paid_from, paid_to = self._bounds(session, zone)
        try:
            outcome = await run_matching(self._matching, merchant_id, paid_from, paid_to)
        except Exception as exc:
            await uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Matching failed while starting reconciliation for merchant {merchant_id}",
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

        await self._finish_onboarding(merchant_id)
        await self._commit(merchant_id, "starting reconciliation")

        sentry_logger.info(
            "Merchant {merchant_id} {action} reconciliation session {session_id}: {matched} "
            "matched, {suggested} suggested, {flagged} flagged",
            merchant_id=str(merchant_id),
            action="started" if created else "continued",
            session_id=str(session.id),
            **outcome.as_dict(),
        )

        view: ReconciliationView = await self._view(session, zone)
        await self._publish(
            merchant_id,
            {"session_id": str(session.id), "totals": view.session.totals.model_dump()},
        )
        return view, created

    async def _finish_onboarding(self, merchant_id: UUID):
        """Starting the first reconciliation while onboarding finishes it"""
        onboarding: MerchantOnboarding | None = await self._uow.repo(
            MerchantOnboardingRepository
        ).get_record(merchant_id=merchant_id, for_update=True)
        if onboarding and onboarding.current_step == OnboardingStep.FIRST_RECONCILIATION:
            now: datetime = datetime.now(UTC)
            onboarding.current_step = OnboardingStep.COMPLETED
            onboarding.completed_at = now
            onboarding.updated_at = now

    async def current(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> ReconciliationView:
        """The open session, else the latest one"""
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        session: ReconciliationSession | None = await self._repo.get_open(
            merchant_id
        ) or await self._repo.latest(merchant_id)
        if not session:
            raise NotFoundError("Reconciliation session")

        return await self._view(session, self._zone(await self._settings(merchant_id)))

    async def get_session(
        self, curr_merchant: Merchant, session_id: UUID, uow: UnitOfWorkRepository
    ) -> ReconciliationView:
        await self._setup_uow(uow)

        session: ReconciliationSession | None = await self._repo.get_record(
            id=session_id, merchant_id=curr_merchant.id
        )
        if not session:
            raise NotFoundError("Reconciliation session")

        return await self._view(session, self._zone(await self._settings(curr_merchant.id)))

    async def list_sessions(
        self, curr_merchant: Merchant, params: PageParams, uow: UnitOfWorkRepository
    ) -> tuple[list[ReconciliationSessionResponse], PageMeta]:
        await self._setup_uow(uow)

        sessions, total = await self._repo.list_sessions(curr_merchant.id, params)
        zone: ZoneInfo = self._zone(await self._settings(curr_merchant.id))

        return [await self._session_response(s, zone) for s in sessions], PageMeta.build(
            params, total
        )

    async def complete(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> ReconciliationSessionResponse:
        """Close the open session with its counts and email the summary"""
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        session: ReconciliationSession | None = await self._repo.get_open(
            merchant_id, for_update=True
        )
        if not session:
            raise NotFoundError("Reconciliation session")

        settings: MerchantSettings | None = await self._settings(merchant_id)
        zone: ZoneInfo = self._zone(settings)
        totals: ReconciliationTotals = await self._totals(session, zone)

        session.total_transactions = totals.total_transactions
        session.matched_count = totals.matched
        # a suggestion nobody confirmed is still an unmatched payment
        session.unmatched_payments_count = totals.unmatched_payments + totals.suggested
        session.unmatched_orders_count = totals.unmatched_orders
        session.flagged_count = totals.flagged
        session.status = ReconciliationSessionStatus.COMPLETED
        session.completed_at = datetime.now(UTC)

        await self._commit(merchant_id, "completing reconciliation")

        sentry_logger.info(
            "Merchant {merchant_id} completed reconciliation session {session_id}",
            merchant_id=str(merchant_id),
            session_id=str(session.id),
        )

        response: ReconciliationSessionResponse = await self._session_response(session, zone)
        await self._notification_service.reconciliation_summary(
            curr_merchant, settings, session, response.totals.model_dump(), uow
        )
        await self._publish(
            merchant_id,
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "totals": response.totals.model_dump(),
            },
        )
        return response

    async def summary(
        self, curr_merchant: Merchant, uow: UnitOfWorkRepository
    ) -> ReconciliationSummary:
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        zone: ZoneInfo = self._zone(await self._settings(merchant_id))
        today_start: datetime = _day_start(datetime.now(zone).date(), zone)

        synced, matched, needs_review = await self._repo.summary_counts(
            merchant_id, today_start, datetime.now(UTC) - timedelta(days=REVIEW_DAYS)
        )
        return ReconciliationSummary(
            synced_today=synced,
            matched_today=matched,
            needs_review=needs_review,
            last_completed_at=await self._repo.last_completed_at(merchant_id),
        )

    # ------------------------------ decisions ------------------------------ #

    async def _lock_pair(
        self, merchant_id: UUID, payload: MatchDecision
    ) -> tuple[
        tuple[Transaction, Customer | None, Order | None], tuple[Order, Customer | None, bool]
    ]:
        # the same lock the matcher holds, so a pass can not link either side meanwhile
        await self._matching.lock(merchant_id)

        found_transaction = await self._repo.get_transaction(
            merchant_id, payload.transaction_id, for_update=True
        )
        if not found_transaction:
            raise NotFoundError("Transaction")
        found_order = await self._repo.get_order(merchant_id, payload.order_id, for_update=True)
        if not found_order:
            raise NotFoundError("Order")
        return found_transaction, found_order

    async def accept_match(
        self, curr_merchant: Merchant, payload: MatchDecision, uow: UnitOfWorkRepository
    ) -> MatchDecisionResponse:
        """Confirm a suggestion: link the payment, the order becomes paid. Accepting a pair
        that is already linked returns it unchanged"""
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        try:
            (transaction, customer, _), (order, order_customer, _) = await self._lock_pair(
                merchant_id, payload
            )

            if transaction.order_id == order.id:
                scores: dict[UUID, ReadinessDetail] = await readiness_for(
                    self._readiness, [transaction]
                )
                return MatchDecisionResponse(
                    transaction=transaction_response(
                        transaction,
                        customer or order_customer,
                        order,
                        readiness_summary(scores.get(transaction.id)),
                    ),
                    totals=await self._open_totals(merchant_id),
                )

            suggestion: MatchSuggestion | None = await self._matching.get_suggestion(
                merchant_id, transaction.id, order.id, for_update=True
            )
            if not suggestion or suggestion.status != MatchSuggestionStatus.PENDING:
                raise NotFoundError("Suggestion")

            if transaction.order_id or transaction.reconciliation_status != (
                ReconciliationStatus.UNMATCHED
            ):
                raise MatchConflictError("already_matched_to_another_order")
            if order.status == OrderStatus.CANCELLED:
                raise MatchConflictError("order_cancelled")
            if not await self._matching.order_is_open(order.id):
                raise MatchConflictError("order_already_settled")

            now: datetime = datetime.now(UTC)
            transaction.order_id = order.id
            transaction.reconciliation_status = ReconciliationStatus.MANUALLY_MATCHED
            transaction.reconciled_at = now
            transaction.match_tier = suggestion.tier
            transaction.match_confidence = suggestion.confidence
            if not transaction.customer_id:
                transaction.customer_id = order.customer_id
            order.status = OrderStatus.PAID
            order.updated_at = now

            await self._matching.drop_pending_for(transaction.id, order.id)
        except AppException:
            await uow.rollback()
            raise

        await self._commit(merchant_id, "accepting a match")

        sentry_logger.info(
            "Merchant {merchant_id} accepted the match of transaction {transaction_id} to "
            "order {order_id}",
            merchant_id=str(merchant_id),
            transaction_id=str(transaction.id),
            order_id=str(order.id),
        )
        return await self._decided(merchant_id, transaction, customer or order_customer, order)

    async def reject_match(
        self, curr_merchant: Merchant, payload: MatchDecision, uow: UnitOfWorkRepository
    ) -> MatchDecisionResponse:
        """Reject a suggestion, or undo an automatic match (the order goes back to pending).
        The pair is never matched or suggested again"""
        await self._setup_uow(uow)
        merchant_id: UUID = curr_merchant.id

        try:
            (transaction, customer, linked_order), (order, _, _) = await self._lock_pair(
                merchant_id, payload
            )
            now: datetime = datetime.now(UTC)

            suggestion: MatchSuggestion | None = await self._matching.get_suggestion(
                merchant_id, transaction.id, order.id, for_update=True
            )
            if suggestion and suggestion.status == MatchSuggestionStatus.PENDING:
                suggestion.status = MatchSuggestionStatus.REJECTED
                suggestion.rejected_at = now
            elif (
                transaction.order_id == order.id
                and transaction.reconciliation_status == ReconciliationStatus.AUTO_MATCHED
            ):
                if order.status == OrderStatus.FULFILLED:
                    raise MatchConflictError("order_fulfilled")

                tier: int = transaction.match_tier or 0
                transaction.order_id = None
                transaction.reconciliation_status = ReconciliationStatus.UNMATCHED
                transaction.reconciled_at = None
                transaction.match_tier = None
                transaction.match_confidence = None
                if order.status == OrderStatus.PAID:
                    order.status = OrderStatus.PENDING
                    order.updated_at = now
                linked_order = None

                await self._matching.reject_pair(merchant_id, transaction.id, order.id, tier, now)
            else:
                raise NotFoundError("Match")
        except AppException:
            await uow.rollback()
            raise

        await self._commit(merchant_id, "rejecting a match")

        sentry_logger.info(
            "Merchant {merchant_id} rejected the match of transaction {transaction_id} to "
            "order {order_id}",
            merchant_id=str(merchant_id),
            transaction_id=str(transaction.id),
            order_id=str(order.id),
        )
        return await self._decided(merchant_id, transaction, customer, linked_order)

    async def _decided(
        self,
        merchant_id: UUID,
        transaction: Transaction,
        customer: Customer | None,
        order: Order | None,
    ) -> MatchDecisionResponse:
        session: ReconciliationSession | None = await self._repo.get_open(merchant_id)
        totals: ReconciliationTotals | None = None
        if session:
            totals = await self._totals(session, self._zone(await self._settings(merchant_id)))

        await self._publish(
            merchant_id,
            {
                "session_id": str(session.id) if session else None,
                "totals": totals.model_dump() if totals else None,
            },
        )
        scores: dict[UUID, ReadinessDetail] = await readiness_for(self._readiness, [transaction])
        return MatchDecisionResponse(
            transaction=transaction_response(
                transaction, customer, order, readiness_summary(scores.get(transaction.id))
            ),
            totals=totals,
        )
