"""Builds a dispute's evidence document: the facts (header, receipt, order, fulfillment,
customer history) read fresh from the database, plus the merchant's editable parts
(narrative, supporting documents, conclusion). The same document feeds the detail page,
the evidence.ready event, the ai's generate step and, frozen at submit, the pdf.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import DisputeCategory
from app.api.models.files import StoredFile
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.disputes import DisputeLinks, DisputeRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.disputes import (
    CustomerHistory,
    EvidenceDocument,
    EvidenceDocumentRef,
    EvidenceHeader,
    FulfillmentEvidence,
    OrderDetails,
    Quality,
    TransactionReceipt,
)

STRONG_FROM: int = 80
MODERATE_FROM: int = 50


def quality_label(score: int) -> str:
    if score >= STRONG_FROM:
        return "strong"
    if score >= MODERATE_FROM:
        return "moderate"
    return "weak"


def quality_of(dispute: Dispute) -> Quality | None:
    if dispute.evidence_quality_score is None:
        return None
    score: int = round(dispute.evidence_quality_score)
    details: dict = dispute.evidence_quality or {}
    suggestions = dispute.evidence_suggestions
    return Quality(
        score=score,
        label=quality_label(score),
        dimension_scores=details.get("dimension_scores"),
        suggestions=suggestions if isinstance(suggestions, list) else [],
        ready_to_submit=details.get("ready_to_submit"),
    )


@dataclass
class EvidenceContext:
    """Everything the document is built from, loaded once"""

    dispute: Dispute
    transaction: Transaction
    customer: Customer | None
    order: Order | None
    fulfillments: list[Fulfillment]
    documents: list[StoredFile]  # attached to the dispute by the merchant
    photos: dict[UUID, list[StoredFile]]  # fulfillment id -> proof photos
    customer_stats: dict | None


def _ref(stored: StoredFile, source: str) -> EvidenceDocumentRef:
    return EvidenceDocumentRef(
        file_id=stored.id, file_name=stored.file_name, caption=stored.caption, source=source
    )


def missing_items(context: EvidenceContext) -> list[str]:
    """What would strengthen the response, from the records alone"""
    category: DisputeCategory | None = context.dispute.category
    missing: list[str] = []
    if not context.order:
        missing.append("A matched order for this payment")
    if category != DisputeCategory.ADMIN_ERROR:
        if not context.fulfillments:
            missing.append("A fulfillment record (delivery or service)")
        elif not any(context.photos.get(f.id) for f in context.fulfillments):
            missing.append("A delivery photo")
        if context.fulfillments and not any(
            f.tracking_number or f.recipient_name for f in context.fulfillments
        ):
            missing.append("A tracking number or signed confirmation")
    if category == DisputeCategory.FRAUD and not (context.customer and context.customer.phone):
        missing.append("The customer's phone number (paystack needs it for fraud claims)")
    return missing


class EvidenceDocumentBuilder:
    def __init__(self, uow: UnitOfWorkRepository):
        self._disputes = uow.repo(DisputeRepository)

    async def load(self, links: DisputeLinks) -> EvidenceContext:
        """Two more queries: the fulfillments, then every file (the dispute's documents and
        the fulfillments' photos) at once"""
        fulfillments: list[Fulfillment] = await self._disputes.fulfillments(links.transaction)
        documents, fulfillment_files = await self._disputes.files_for(
            links.dispute.id, [f.id for f in fulfillments]
        )
        photos: dict[UUID, list[StoredFile]] = {}
        for stored in fulfillment_files:
            photos.setdefault(stored.fulfillment_id, []).append(stored)

        return EvidenceContext(
            dispute=links.dispute,
            transaction=links.transaction,
            customer=links.customer,
            order=links.order,
            fulfillments=fulfillments,
            documents=documents,
            photos=photos,
            customer_stats=links.history,
        )

    @staticmethod
    def build(merchant: Merchant, context: EvidenceContext) -> EvidenceDocument:
        dispute, transaction, order = context.dispute, context.transaction, context.order
        customer = context.customer
        stats = context.customer_stats

        history: CustomerHistory | None = None
        # this dispute counts as one; earlier payments make the relationship worth stating
        if stats and stats.get("payment_count", 0) > 1:
            history = CustomerHistory(
                payment_count=stats["payment_count"],
                first_payment_at=stats.get("first_payment_at"),
                prior_disputes=max(stats.get("dispute_count", 0) - 1, 0),
            )

        return EvidenceDocument(
            version=dispute.evidence_version,
            generation_source=dispute.generation_source,
            generated_at=dispute.generated_at,
            edited_at=dispute.edited_at,
            header=EvidenceHeader(
                business_name=merchant.business_name,
                paystack_integration_id=merchant.paystack_integration_id,
                document_date=datetime.now(UTC),
                dispute_reference=str(dispute.paystack_dispute_id),
                transaction_reference=transaction.paystack_reference,
            ),
            transaction_receipt=TransactionReceipt(
                paid_at=transaction.paid_at,
                amount=transaction.amount,
                currency=transaction.currency,
                channel=transaction.channel,
                reference=transaction.paystack_reference,
                customer_email=transaction.customer_email or (customer and customer.email),
                customer_name=transaction.customer_name or (customer and customer.name),
            ),
            order_details=(
                OrderDetails(
                    order_number=order.order_number,
                    description=order.description,
                    created_at=order.created_at,
                    amount=order.amount,
                    currency=order.currency,
                )
                if order
                else None
            ),
            fulfillment_evidence=[
                FulfillmentEvidence(
                    type=f.type,
                    delivery_date=f.delivery_date,
                    tracking_number=f.tracking_number,
                    recipient_name=f.recipient_name,
                    delivery_address=f.delivery_address,
                    notes=f.notes,
                    photos=[_ref(p, "fulfillment") for p in context.photos.get(f.id, [])],
                )
                for f in context.fulfillments
            ],
            narrative=dispute.evidence_narrative,
            supporting_documents=[_ref(d, "merchant") for d in context.documents],
            customer_history=history,
            conclusion=dispute.evidence_conclusion,
            # from the records every time, so adding a photo clears it at once (the ai's own
            # list goes stale and feeds its suggestions instead)
            missing_evidence=missing_items(context),
            quality=quality_of(dispute),
        )

    @staticmethod
    def object_names(context: EvidenceContext) -> dict[str, str]:
        """file id -> bucket key for every image in the document, for the pdf (internal:
        kept in the submitted snapshot, never returned to clients)"""
        files: list[StoredFile] = list(context.documents)
        for photos in context.photos.values():
            files.extend(photos)
        return {str(f.id): f.object_name for f in files}

    @staticmethod
    def ai_context(document: EvidenceDocument, dispute: Dispute) -> dict:
        """The generate step's input package (spec 4.2 and 16.1)"""
        facts: dict = document.model_dump(
            mode="json",
            include={
                "transaction_receipt",
                "order_details",
                "fulfillment_evidence",
                "customer_history",
                "supporting_documents",
            },
        )
        return {
            "disputeId": str(dispute.id),
            "category": dispute.category.value if dispute.category else None,
            "submissionFlow": dispute.submission_flow.value if dispute.submission_flow else None,
            "reason": dispute.reason_raw,
            "dueAt": dispute.due_at.isoformat(),
            "transaction": facts["transaction_receipt"],
            "order": facts["order_details"],
            "fulfillment": facts["fulfillment_evidence"],
            "customerHistory": facts["customer_history"],
            "supportingDocuments": facts["supporting_documents"],
            "evidenceStrategy": dispute.evidence_strategy,
            "specialInstructions": dispute.special_instructions,
        }
