from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.models.enums import (
    Currency,
    DisputeCategory,
    DisputeStatus,
    EvidenceState,
    EvidenceStep,
    FulfillmentType,
    GenerationSource,
    SubmissionFlow,
    SubmissionState,
    TransactionChannel,
)
from app.api.schemas.auth import AuthBase
from app.api.schemas.customers import CustomerRef
from app.api.schemas.pagination import PageMeta, PageParams
from app.api.schemas.readiness import Readiness, ReadinessDetail

Urgency = Literal["critical", "warning", "safe"]
QualityLabel = Literal["strong", "moderate", "weak"]
DisputeSort = Literal["created_at", "-created_at", "due_at", "-due_at"]
DisputeAction = Literal["generate_evidence", "edit_evidence", "submit", "accept", "download_pdf"]


def _split_comma_list(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return [item.strip() for item in value[0].split(",") if item.strip()]
    return value


class DisputeListQuery(PageParams):
    # comma lists, e.g. ?status=pending,evidence_generated&urgency=critical,warning
    status: list[DisputeStatus] | None = None
    category: list[DisputeCategory] | None = None
    urgency: list[Urgency] | None = None
    sort: DisputeSort = "-created_at"

    _split_lists = field_validator("status", "category", "urgency", mode="before")(
        _split_comma_list
    )


class DisputePageMeta(PageMeta):
    # for the countdowns: due_at minus server_time, not the device clock
    server_time: datetime


class Quality(BaseModel):
    score: int
    label: QualityLabel
    dimension_scores: dict[str, int] | None = None
    suggestions: list[str] = []
    ready_to_submit: bool | None = None


class DisputeCustomer(BaseModel):
    name: str | None
    email: str | None


class DisputeSummary(BaseModel):
    """A dispute as listed"""

    id: UUID
    paystack_dispute_id: str
    status: DisputeStatus
    paystack_status: str | None
    category: DisputeCategory | None
    # the bank's reason, as paystack sent it
    reason: str | None
    amount: int
    currency: Currency
    created_at: datetime
    due_at: datetime
    # null once the merchant no longer has to respond
    urgency: Urgency | None
    customer: DisputeCustomer | None
    transaction_reference: str
    readiness: Readiness | None
    quality: Quality | None
    evidence_state: EvidenceState | None
    submission_state: SubmissionState | None


# ------------------------------ the evidence document ------------------------------ #
# Sections in the order of the pdf. Facts come from the database every time the document
# is built; narrative, supporting documents and conclusion are the merchant's to edit.


class EvidenceHeader(BaseModel):
    business_name: str
    paystack_integration_id: str | None
    document_date: datetime
    dispute_reference: str
    transaction_reference: str


class TransactionReceipt(BaseModel):
    paid_at: datetime | None
    amount: int
    currency: Currency
    channel: TransactionChannel
    reference: str
    customer_email: str | None
    customer_name: str | None


class OrderDetails(BaseModel):
    order_number: str | None
    description: str | None
    created_at: datetime
    amount: int
    currency: Currency


class EvidenceDocumentRef(BaseModel):
    file_id: UUID
    file_name: str
    caption: str | None
    # fulfillment: a proof photo of the order's fulfillment (included automatically);
    # merchant: attached to this dispute
    source: Literal["fulfillment", "merchant"]


class FulfillmentEvidence(BaseModel):
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None
    recipient_name: str | None
    delivery_address: str | None
    notes: str | None
    photos: list[EvidenceDocumentRef]


class CustomerHistory(BaseModel):
    payment_count: int
    first_payment_at: datetime | None
    # other disputes this customer raised with the merchant
    prior_disputes: int


class EvidenceDocument(BaseModel):
    version: int
    generation_source: GenerationSource | None
    generated_at: datetime | None
    edited_at: datetime | None
    header: EvidenceHeader
    transaction_receipt: TransactionReceipt
    order_details: OrderDetails | None
    fulfillment_evidence: list[FulfillmentEvidence]
    narrative: str | None
    supporting_documents: list[EvidenceDocumentRef]
    # omitted for shared emails and first-time customers
    customer_history: CustomerHistory | None
    conclusion: str | None
    missing_evidence: list[str]
    quality: Quality | None
    editable: list[str] = ["narrative", "supporting_documents", "conclusion"]


class DisputeDetail(DisputeSummary):
    server_time: datetime
    category_confidence: float | None
    submission_flow: SubmissionFlow | None
    special_instructions: str | None
    evidence_step: EvidenceStep | None
    submission_error: str | None
    submitted_at: datetime | None
    resolved_at: datetime | None
    allowed_actions: list[DisputeAction]
    # set when the facts suggest conceding, e.g. a real duplicate charge
    recommendation: Literal["accept"] | None
    readiness: ReadinessDetail | None
    evidence: EvidenceDocument
    customer: CustomerRef | None


# ------------------------------ requests ------------------------------ #


class EvidenceDocumentInput(AuthBase):
    file_id: UUID
    caption: str | None = Field(None, max_length=255)


class EvidenceUpdate(AuthBase):
    # the evidence version the edit was made on; a stale one gets 409
    version: int = Field(..., ge=0)
    narrative: str | None = Field(None, min_length=1, max_length=20_000)
    conclusion: str | None = Field(None, min_length=1, max_length=5_000)
    # the complete set of attached documents (uploads from /uploads); fulfillment photos
    # are included on their own
    documents: list[EvidenceDocumentInput] | None = Field(None, max_length=10)
    # why it changed, kept with the revision ("added the courier's delivery photo")
    reason: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_change(self) -> "EvidenceUpdate":
        if self.narrative is None and self.conclusion is None and self.documents is None:
            raise ValueError("send narrative, conclusion or documents")
        if self.documents is not None:
            ids = [document.file_id for document in self.documents]
            if len(ids) != len(set(ids)):
                raise ValueError("a document is listed twice")
        return self


class EvidenceSubmit(AuthBase):
    # the version the merchant approved; a stale one gets 409
    version: int = Field(..., ge=1)


class DisputeAccept(AuthBase):
    message: str | None = Field(None, min_length=1, max_length=500)


class EvidenceQueued(BaseModel):
    dispute_id: UUID
    evidence_state: EvidenceState
    evidence_step: EvidenceStep | None


class SubmissionQueued(BaseModel):
    dispute_id: UUID
    submission_state: SubmissionState


class DisputeSyncQueued(BaseModel):
    status: Literal["queued"] = "queued"


class DisputeStats(BaseModel):
    total: int
    open: int
    submitted: int
    won: int
    lost: int
    auto_accepted: int
    # won out of those resolved after the merchant responded
    win_rate: float | None
    # hours from the dispute opening to the merchant's response
    avg_response_hours: float | None
