"""Pre-written fallbacks for when the ai fails or does not answer in time: a keyword
classifier (the detection signals of spec section 15.2) and a narrative and conclusion per
category, built only from the facts on record. Nothing here invents a data point.
"""

from app.api.models.enums import DisputeCategory, SubmissionFlow
from app.api.schemas.disputes import EvidenceDocument

# category -> phrases in the bank's text, checked in this order: fraud first, since it needs
# the extra identity step and is the costlier one to miss
SIGNALS: tuple[tuple[DisputeCategory, tuple[str, ...]], ...] = (
    (
        DisputeCategory.FRAUD,
        (
            "unauthori",
            "did not authori",
            "fraud",
            "stolen",
            "not in possession",
            "did not make",
        ),
    ),
    (
        DisputeCategory.ADMIN_ERROR,
        ("duplicate", "charged twice", "double debit", "wrong amount", "overcharged", "refund not"),
    ),
    (
        DisputeCategory.CHARGEBACK_NOT_AS_DESCRIBED,
        ("not as described", "different from", "wrong item", "quality", "defective", "materially"),
    ),
    (
        DisputeCategory.CHARGEBACK_NO_VALUE,
        ("no value", "not received", "debited but", "not delivered", "not rendered"),
    ),
)
# when the text matches nothing, the most common kind, with low confidence
DEFAULT_CATEGORY: DisputeCategory = DisputeCategory.CHARGEBACK_NO_VALUE
MATCHED_CONFIDENCE: float = 0.6
DEFAULT_CONFIDENCE: float = 0.3


def classify_by_keywords(reason: str | None) -> tuple[DisputeCategory, float]:
    text: str = (reason or "").lower()
    for category, phrases in SIGNALS:
        if any(phrase in text for phrase in phrases):
            return category, MATCHED_CONFIDENCE
    return DEFAULT_CATEGORY, DEFAULT_CONFIDENCE


def submission_flow(category: DisputeCategory | None) -> SubmissionFlow:
    return (
        SubmissionFlow.FRAUD_FLOW
        if category == DisputeCategory.FRAUD
        else SubmissionFlow.CHARGEBACK_FLOW
    )


def _money(amount: int, currency: str) -> str:
    return f"{currency} {amount / 100:,.2f}"


def template_narrative(document: EvidenceDocument, category: DisputeCategory | None) -> str:
    """The five sections of spec 16.2 from the facts on record; a section with no facts
    behind it is left out rather than guessed"""
    receipt = document.transaction_receipt
    order = document.order_details
    paragraphs: list[str] = []

    paid: str = f"On {receipt.paid_at:%d %B %Y}, " if receipt.paid_at else ""
    customer: str = receipt.customer_name or receipt.customer_email or "the customer"
    purpose: str = f" for {order.description}" if order and order.description else ""
    paragraphs.append(
        f"{paid}{customer} made a payment of {_money(receipt.amount, receipt.currency)} "
        f"via {receipt.channel.value.replace('_', ' ')}{purpose}. The transaction was "
        f"processed successfully with reference {receipt.reference}."
    )

    if document.fulfillment_evidence:
        fulfillment = document.fulfillment_evidence[0]
        line: str = (
            f"The order was fulfilled ({fulfillment.type.value.replace('_', ' ')}) on "
            f"{fulfillment.delivery_date:%d %B %Y}."
        )
        if fulfillment.recipient_name:
            line += f" It was received by {fulfillment.recipient_name}"
            line += f" at {fulfillment.delivery_address}." if fulfillment.delivery_address else "."
        if fulfillment.tracking_number:
            line += f" Tracking number: {fulfillment.tracking_number}."
        paragraphs.append(line)
    # without a fulfillment the gap is listed for the merchant (missing_evidence), never
    # stated to the bank

    items: list[str] = ["Transaction receipt confirming the successful payment."]
    if order:
        items.append("The merchant's order record.")
    photos: int = sum(len(f.photos) for f in document.fulfillment_evidence) + len(
        document.supporting_documents
    )
    if photos:
        items.append(f"{photos} supporting photo{'s' if photos != 1 else ''} or document(s).")
    paragraphs.append(
        "Attached to this response: "
        + " ".join(f"({number}) {item}" for number, item in enumerate(items, start=1))
    )

    history = document.customer_history
    if history and history.payment_count > 1 and not history.prior_disputes:
        since: str = f" since {history.first_payment_at:%B %Y}" if history.first_payment_at else ""
        paragraphs.append(
            f"The customer has paid this merchant{since}, with {history.payment_count} "
            "successful payments and no prior disputes."
        )

    return "\n\n".join(paragraphs)


def template_conclusion(category: DisputeCategory | None) -> str:
    if category == DisputeCategory.FRAUD:
        return (
            "Based on the evidence provided, the merchant respectfully requests that this "
            "dispute be resolved in its favour. The payment was completed by the customer on "
            "record and the supporting documentation is attached."
        )
    return (
        "Based on the evidence provided, the merchant respectfully requests that this dispute "
        "be resolved in its favour. The payment was authorised, value was delivered, and "
        "supporting documentation is attached."
    )


def acceptance_message(message: str | None) -> str:
    return message or "The merchant accepts this dispute and agrees to the refund."
