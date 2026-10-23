"""Disputes for the merchant: listing, the detail page, evidence (generate, edit, approve)
and the response to paystack (submit or accept), which runs in the background."""

from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from redis.asyncio import Redis
from starlette.concurrency import run_in_threadpool

from app.api.clients.minio import MinioStorage
from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeCategory,
    EvidenceChange,
    EvidenceState,
    EvidenceStep,
    SubmissionFlow,
    SubmissionState,
)
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.files import StoredFile
from app.api.models.merchants import Merchant
from app.api.repo.disputes import (
    AWAITING_STATUSES,
    CRITICAL_HOURS,
    WARNING_HOURS,
    DisputeLinks,
    DisputeRepository,
)
from app.api.repo.ai_memory import AiMemoryRepository
from app.api.repo.files import FileRepository
from app.api.repo.readiness import ReadinessRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.customers import CustomerRef
from app.api.schemas.disputes import (
    DisputeAccept,
    DisputeCustomer,
    DisputeDetail,
    DisputeListQuery,
    DisputePageMeta,
    DisputeStats,
    DisputeSummary,
    DisputeSyncQueued,
    EvidenceDocument,
    EvidenceQueued,
    EvidenceSubmit,
    EvidenceUpdate,
    SubmissionQueued,
)
from app.api.schemas.pagination import PageMeta
from app.api.schemas.readiness import ReadinessDetail
from app.api.services.dispute_ai import EvidenceChain
from app.api.services.evidence_document import (
    EvidenceContext,
    EvidenceDocumentBuilder,
    quality_of,
)
from app.api.services.evidence_templates import submission_flow
from app.api.services.readiness import readiness_for, readiness_for_payments
from app.api.services.readiness import summary as readiness_summary
from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    DisputeActionNotAllowedError,
    EvidenceVersionConflictError,
    FileAlreadyAttachedError,
    FraudEvidenceIncompleteError,
    NotFoundError,
    PaystackNotConnectedError,
    ServerError,
)
from app.worker.tasks.dispute_submission import accept_dispute, submit_dispute
from app.worker.tasks.disputes import poll_disputes

SETTINGS = get_settings()

# paystack statuses after which the merchant can no longer respond
RESPONDED_STATUSES: tuple[str, ...] = ("awaiting-bank-feedback", "resolved", "archived")
IN_FLIGHT: tuple[SubmissionState, ...] = (SubmissionState.SUBMITTING, SubmissionState.ACCEPTING)
DONE: tuple[SubmissionState, ...] = (SubmissionState.SUBMITTED, SubmissionState.ACCEPTED)
# a submission or acceptance goes ahead of syncs: the deadline is near
SUBMISSION_PRIORITY: int = 8


def urgency(dispute: Dispute, now: datetime) -> str | None:
    if dispute.status not in AWAITING_STATUSES:
        return None
    hours: float = (dispute.due_at - now).total_seconds() / 3600
    if hours < CRITICAL_HOURS:
        return "critical"
    if hours < WARNING_HOURS:
        return "warning"
    return "safe"


def _blocked(dispute: Dispute, now: datetime) -> str | None:
    """Why the merchant can not respond at all, if they can't"""
    if dispute.status not in AWAITING_STATUSES:
        return "already_responded_or_resolved"
    if dispute.paystack_status in RESPONDED_STATUSES:
        return "already_responded_or_resolved"
    if dispute.submission_state in IN_FLIGHT:
        return "response_in_progress"
    if dispute.submission_state in DONE:
        return "already_responded_or_resolved"
    if dispute.due_at <= now:
        return "deadline_passed"
    return None


def allowed_actions(dispute: Dispute, now: datetime) -> list[str]:
    actions: list[str] = []
    if not _blocked(dispute, now):
        if dispute.evidence_state != EvidenceState.GENERATING:
            actions += ["generate_evidence", "edit_evidence"]
            if dispute.evidence_narrative:
                actions.append("submit")
        actions.append("accept")
    if dispute.evidence_pdf_object:
        actions.append("download_pdf")
    return actions


class DisputeService:
    def __init__(self, redis: Redis):
        self._redis = redis

    def _setup(self, uow: UnitOfWorkRepository):
        self._uow = uow
        self._disputes = uow.repo(DisputeRepository)
        self._builder = EvidenceDocumentBuilder(uow)
        self._memory = uow.repo(AiMemoryRepository)

    async def _remember_revision(self, merchant: Merchant, revision: EvidenceRevision):
        await self._uow.flush()
        await self._memory.remember(
            tenant_id=merchant.id,
            merchant_id=merchant.id,
            dispute_id=revision.dispute_id,
            memory_type="evidence_revision",
            source_type="evidence_revision",
            source_id=str(revision.id),
            content={
                "version": revision.version,
                "change": revision.change.value,
                "reason": revision.reason,
                "narrative": revision.narrative,
                "conclusion": revision.conclusion,
            },
            occurred_at=revision.created_at,
        )

    async def _get(
        self, merchant: Merchant, dispute_id: UUID, for_update: bool = False
    ) -> DisputeLinks:
        """The dispute with what its evidence is built from, in one query"""
        found: DisputeLinks | None = await self._disputes.get_with_links(
            merchant.id, dispute_id, for_update
        )
        if not found:
            raise NotFoundError("Dispute")
        return found

    async def _get_dispute(
        self, merchant: Merchant, dispute_id: UUID, for_update: bool = False
    ) -> Dispute:
        """The dispute row alone, for actions that need nothing linked"""
        dispute: Dispute | None = await self._disputes.get_for_merchant(
            merchant.id, dispute_id, for_update
        )
        if not dispute:
            raise NotFoundError("Dispute")
        return dispute

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

    # ------------------------------ reads ------------------------------ #

    @staticmethod
    def _summary_fields(
        dispute: Dispute,
        reference: str,
        name: str | None,
        email: str | None,
        now: datetime,
    ) -> dict:
        return {
            "id": dispute.id,
            "paystack_dispute_id": str(dispute.paystack_dispute_id),
            "status": dispute.status,
            "paystack_status": dispute.paystack_status,
            "category": dispute.category,
            "reason": dispute.reason_raw,
            "amount": dispute.amount,
            "currency": dispute.currency,
            "created_at": dispute.created_at,
            "due_at": dispute.due_at,
            "urgency": urgency(dispute, now),
            "transaction_reference": reference,
            "quality": quality_of(dispute),
            "evidence_state": dispute.evidence_state,
            "submission_state": dispute.submission_state,
        }

    async def list_disputes(
        self, merchant: Merchant, query: DisputeListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[DisputeSummary], DisputePageMeta]:
        """Two queries: the page (only the columns shown) and the page's readiness"""
        self._setup(uow)
        now: datetime = datetime.now(UTC)
        rows, total = await self._disputes.list_disputes(merchant.id, query, now)
        scores: dict[UUID, ReadinessDetail] = await readiness_for_payments(
            uow.repo(ReadinessRepository),
            [(row.transaction_id, row.order_id, row.reconciliation_status) for row in rows],
        )

        disputes: list[DisputeSummary] = [
            DisputeSummary(
                **self._summary_fields(
                    row.Dispute, row.paystack_reference, row.customer_name, row.customer_email, now
                ),
                customer=(
                    DisputeCustomer(name=row.customer_name, email=row.customer_email)
                    if row.customer_name or row.customer_email
                    else None
                ),
                readiness=readiness_summary(scores.get(row.transaction_id)),
            )
            for row in rows
        ]

        meta = DisputePageMeta(**PageMeta.build(query, total).model_dump(), server_time=now)
        return disputes, meta

    async def _detail(self, merchant: Merchant, links: DisputeLinks) -> DisputeDetail:
        """Four queries in all with the links: fulfillments, files and readiness (plus the
        duplicate check, for admin_error claims only)"""
        dispute, transaction, customer = links.dispute, links.transaction, links.customer
        now: datetime = datetime.now(UTC)
        context: EvidenceContext = await self._builder.load(links)
        document: EvidenceDocument = self._builder.build(merchant, context)
        scores: dict[UUID, ReadinessDetail] = await readiness_for(
            self._uow.repo(ReadinessRepository), [transaction]
        )

        recommendation: str | None = None
        if (
            dispute.category == DisputeCategory.ADMIN_ERROR
            and await self._disputes.duplicate_charges(transaction) > 0
        ):
            # the customer really was charged twice: conceding beats fighting
            recommendation = "accept"

        receipt = document.transaction_receipt
        return DisputeDetail(
            **self._summary_fields(
                dispute,
                transaction.paystack_reference,
                receipt.customer_name,
                receipt.customer_email,
                now,
            ),
            customer=CustomerRef.model_validate(customer) if customer else None,
            readiness=scores.get(transaction.id),
            server_time=now,
            category_confidence=dispute.category_confidence,
            submission_flow=dispute.submission_flow,
            special_instructions=dispute.special_instructions,
            evidence_step=dispute.evidence_step,
            submission_error=dispute.submission_error,
            submitted_at=dispute.submitted_at,
            resolved_at=dispute.resolved_at,
            allowed_actions=allowed_actions(dispute, now),
            recommendation=recommendation,
            evidence=document,
        )

    async def get_dispute(
        self, merchant: Merchant, dispute_id: UUID, uow: UnitOfWorkRepository
    ) -> DisputeDetail:
        self._setup(uow)
        return await self._detail(merchant, await self._get(merchant, dispute_id))

    async def stats(self, merchant: Merchant, uow: UnitOfWorkRepository) -> DisputeStats:
        self._setup(uow)
        counts: dict = await self._disputes.stats(merchant.id)
        decided: int = counts.pop("decided_after_response")
        avg_hours: float | None = counts.pop("avg_response_hours")
        return DisputeStats(
            **counts,
            win_rate=round(counts["won"] * 100 / decided, 1) if decided else None,
            avg_response_hours=round(avg_hours, 1) if avg_hours is not None else None,
        )

    async def sync(self, merchant: Merchant) -> DisputeSyncQueued:
        """Queue a poll of paystack for the merchant's disputes"""
        if not merchant.paystack_secret_key:
            raise PaystackNotConnectedError()
        try:
            await run_in_threadpool(
                poll_disputes.apply_async,
                kwargs={"merchant_id": str(merchant.id)},
                priority=SUBMISSION_PRIORITY,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            raise ServerError() from exc
        return DisputeSyncQueued()

    # ------------------------------ evidence ------------------------------ #

    async def generate_evidence(
        self, merchant: Merchant, dispute_id: UUID, uow: UnitOfWorkRepository
    ) -> EvidenceQueued:
        """Starts the ai chain; a chain already running is returned as it is. Classification
        is kept from an earlier run, so regenerating starts at the narrative"""
        self._setup(uow)
        dispute: Dispute = await self._get_dispute(merchant, dispute_id, for_update=True)

        if dispute.evidence_state != EvidenceState.GENERATING:
            reason: str | None = _blocked(dispute, datetime.now(UTC))
            if reason:
                await uow.rollback()
                raise DisputeActionNotAllowedError("generate evidence", reason)
            step: EvidenceStep = (
                EvidenceStep.GENERATE if dispute.category else EvidenceStep.CLASSIFY
            )
            await EvidenceChain(uow, self._redis).send(merchant, dispute, step)
            sentry_logger.info(
                "Merchant {merchant_id} started evidence for dispute {dispute_id}",
                merchant_id=str(merchant.id),
                dispute_id=str(dispute.id),
            )

        return EvidenceQueued(
            dispute_id=dispute.id,
            evidence_state=dispute.evidence_state,
            evidence_step=dispute.evidence_step,
        )

    async def _set_documents(self, merchant: Merchant, dispute: Dispute, documents: list) -> bool:
        """Makes the dispute's attachments exactly documents; returns whether the set of
        files changed (captions alone do not count)"""
        current: dict[UUID, StoredFile] = {
            f.id: f for f in await self._disputes.documents_for_update(dispute.id)
        }
        wanted: dict[UUID, str | None] = {d.file_id: d.caption for d in documents}

        new_ids: list[UUID] = [file_id for file_id in wanted if file_id not in current]
        found: dict[UUID, StoredFile] = {
            f.id: f
            for f in await self._uow.repo(FileRepository).lock_for_merchant(merchant.id, new_ids)
        }
        for file_id in new_ids:
            stored: StoredFile | None = found.get(file_id)
            if stored is None:
                raise NotFoundError("File")
            if stored.fulfillment_id or stored.dispute_id:
                raise FileAlreadyAttachedError(str(file_id))
            stored.dispute_id = dispute.id
            current[file_id] = stored

        removed: list[UUID] = [file_id for file_id in current if file_id not in wanted]
        for file_id in removed:
            # detached uploads become unattached; the cleanup task deletes them later
            current[file_id].dispute_id = None
            current[file_id].caption = None
        for file_id, caption in wanted.items():
            current[file_id].caption = caption

        return bool(new_ids or removed)

    async def update_evidence(
        self,
        merchant: Merchant,
        dispute_id: UUID,
        payload: EvidenceUpdate,
        uow: UnitOfWorkRepository,
    ) -> DisputeDetail:
        """The merchant's edit: narrative, conclusion and attached documents. Facts are not
        editable here; they change at their source (order, fulfillment)"""
        self._setup(uow)
        links: DisputeLinks = await self._get(merchant, dispute_id, for_update=True)
        dispute: Dispute = links.dispute
        now: datetime = datetime.now(UTC)

        try:
            reason: str | None = _blocked(dispute, now)
            if reason or dispute.evidence_state == EvidenceState.GENERATING:
                raise DisputeActionNotAllowedError("edit evidence", reason or "evidence_generating")
            if payload.version != dispute.evidence_version:
                raise EvidenceVersionConflictError(dispute.evidence_version)

            text_changed: bool = False
            if payload.narrative is not None and payload.narrative != dispute.evidence_narrative:
                dispute.evidence_narrative = payload.narrative
                text_changed = True
            if payload.conclusion is not None and payload.conclusion != dispute.evidence_conclusion:
                dispute.evidence_conclusion = payload.conclusion
                text_changed = True
            documents_changed: bool = False
            if payload.documents is not None:
                documents_changed = await self._set_documents(merchant, dispute, payload.documents)
        except AppException:
            await uow.rollback()
            raise

        change: EvidenceChange = (
            EvidenceChange.TEXT_AND_DOCUMENTS
            if text_changed and documents_changed
            else EvidenceChange.DOCUMENTS
            if documents_changed
            else EvidenceChange.TEXT
        )
        dispute.evidence_version += 1
        dispute.edited_at = now
        if dispute.evidence_state is None:
            # written by hand without generating first
            dispute.evidence_state = EvidenceState.READY

        context: EvidenceContext = await self._builder.load(links)
        revision = self._disputes.add_revision(
            EvidenceRevision(
                dispute_id=dispute.id,
                merchant_id=merchant.id,
                version=dispute.evidence_version,
                change=change,
                reason=payload.reason,
                narrative=dispute.evidence_narrative,
                conclusion=dispute.evidence_conclusion,
                documents=[{"file_id": str(d.id), "caption": d.caption} for d in context.documents],
                created_at=now,
            )
        )
        await self._remember_revision(merchant, revision)
        await self._commit(merchant.id, "editing dispute evidence")

        sentry_logger.info(
            "Merchant {merchant_id} edited evidence for dispute {dispute_id} ({change})",
            merchant_id=str(merchant.id),
            dispute_id=str(dispute.id),
            change=change.value,
        )
        return await self._detail(merchant, links)

    # ------------------------------ responding ------------------------------ #

    @staticmethod
    def _fraud_evidence(document: EvidenceDocument, customer: Customer | None) -> dict:
        """POST /dispute/:id/evidence fields; paystack requires email, name, phone and
        service details"""
        receipt = document.transaction_receipt
        fulfillment = document.fulfillment_evidence[0] if document.fulfillment_evidence else None
        order = document.order_details
        service: str | None = (order.description if order else None) or (
            (document.narrative or "").split("\n\n")[0][:500] or None
        )
        fields: dict = {
            "customer_email": receipt.customer_email,
            "customer_name": receipt.customer_name,
            "customer_phone": customer.phone if customer else None,
            "service_details": service,
            "delivery_address": fulfillment.delivery_address if fulfillment else None,
            "delivery_date": (
                fulfillment.delivery_date.date().isoformat() if fulfillment else None
            ),
        }
        missing: list[str] = [
            name
            for name in ("customer_email", "customer_name", "customer_phone", "service_details")
            if not fields[name]
        ]
        if missing:
            raise FraudEvidenceIncompleteError(missing)
        return fields

    async def _queue(self, task, kwargs: dict):
        try:
            await run_in_threadpool(task.apply_async, kwargs=kwargs, priority=SUBMISSION_PRIORITY)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Dispute response could not be queued")
            raise ServerError() from exc

    async def submit(
        self,
        merchant: Merchant,
        dispute_id: UUID,
        payload: EvidenceSubmit,
        uow: UnitOfWorkRepository,
    ) -> SubmissionQueued:
        """Freezes the approved version (facts included) and queues the submission: pdf,
        then paystack's chargeback or fraud flow"""
        self._setup(uow)
        links: DisputeLinks = await self._get(merchant, dispute_id, for_update=True)
        dispute, customer = links.dispute, links.customer
        now: datetime = datetime.now(UTC)

        try:
            reason: str | None = _blocked(dispute, now)
            if not reason and dispute.evidence_state == EvidenceState.GENERATING:
                reason = "evidence_generating"
            if not reason and not dispute.evidence_narrative:
                reason = "no_evidence"
            if reason:
                raise DisputeActionNotAllowedError("submit", reason)
            if payload.version != dispute.evidence_version:
                raise EvidenceVersionConflictError(dispute.evidence_version)

            context: EvidenceContext = await self._builder.load(links)
            document: EvidenceDocument = self._builder.build(merchant, context)
            flow: SubmissionFlow = dispute.submission_flow or submission_flow(dispute.category)
            fraud: dict | None = (
                self._fraud_evidence(document, customer)
                if flow == SubmissionFlow.FRAUD_FLOW
                else None
            )
        except AppException:
            await uow.rollback()
            raise

        dispute.submission_flow = flow
        dispute.submission_state = SubmissionState.SUBMITTING
        dispute.submission_error = None
        # a new approval: the task's own retries resume, but a new submit renders and
        # uploads the approved version afresh
        dispute.evidence_pdf_object = None
        dispute.paystack_uploaded_filename = None
        dispute.evidence_version += 1
        revision = self._disputes.add_revision(
            EvidenceRevision(
                dispute_id=dispute.id,
                merchant_id=merchant.id,
                version=dispute.evidence_version,
                change=EvidenceChange.SUBMITTED,
                reason="Approved and submitted",
                narrative=dispute.evidence_narrative,
                conclusion=dispute.evidence_conclusion,
                documents=[{"file_id": str(d.id), "caption": d.caption} for d in context.documents],
                # what the pdf is rendered from, exactly as approved
                snapshot={
                    "document": document.model_dump(mode="json"),
                    "files": self._builder.object_names(context),
                    "submission_flow": flow.value,
                    "fraud_evidence": fraud,
                },
                created_at=now,
            )
        )
        await self._remember_revision(merchant, revision)
        await self._commit(merchant.id, "submitting a dispute")
        await self._queue(submit_dispute, {"dispute_id": str(dispute.id)})

        sentry_logger.info(
            "Merchant {merchant_id} submitted dispute {dispute_id} ({flow})",
            merchant_id=str(merchant.id),
            dispute_id=str(dispute.id),
            flow=flow.value,
        )
        return SubmissionQueued(dispute_id=dispute.id, submission_state=dispute.submission_state)

    async def accept(
        self,
        merchant: Merchant,
        dispute_id: UUID,
        payload: DisputeAccept,
        uow: UnitOfWorkRepository,
    ) -> SubmissionQueued:
        """Concede the dispute (the customer is refunded); runs in the background"""
        self._setup(uow)
        dispute: Dispute = await self._get_dispute(merchant, dispute_id, for_update=True)

        reason: str | None = _blocked(dispute, datetime.now(UTC))
        if reason:
            await uow.rollback()
            raise DisputeActionNotAllowedError("accept", reason)

        dispute.submission_state = SubmissionState.ACCEPTING
        dispute.submission_error = None
        # the acceptance letter replaces any evidence a failed submit uploaded
        dispute.paystack_uploaded_filename = None
        await self._commit(merchant.id, "accepting a dispute")
        await self._queue(
            accept_dispute, {"dispute_id": str(dispute.id), "message": payload.message}
        )

        sentry_logger.info(
            "Merchant {merchant_id} accepted dispute {dispute_id}",
            merchant_id=str(merchant.id),
            dispute_id=str(dispute.id),
        )
        return SubmissionQueued(dispute_id=dispute.id, submission_state=dispute.submission_state)

    async def evidence_pdf(
        self,
        merchant: Merchant,
        dispute_id: UUID,
        uow: UnitOfWorkRepository,
        storage: MinioStorage,
    ) -> tuple[bytes, str]:
        self._setup(uow)
        dispute: Dispute = await self._get_dispute(merchant, dispute_id)
        if not dispute.evidence_pdf_object:
            raise NotFoundError("Evidence PDF")
        content: bytes = await storage.retrieve(SETTINGS.MINIO_BUCKET, dispute.evidence_pdf_object)
        return content, f"dispute-{dispute.paystack_dispute_id}-evidence.pdf"
