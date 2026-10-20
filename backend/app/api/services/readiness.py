"""Dispute readiness: how much defensible evidence a matched payment has (0-100).

Computed when read, from what is in the database, so adding a fulfillment or a photo shows
up at once. Only matched payments (auto_matched or manually_matched) have a score; the rest
get null. One query covers a whole page of payments.

Component                                              Points
Transaction record exists                              20
Linked to a merchant order                             15
Customer record with an email or phone                 10
Fulfillment recorded (on the payment or its order)     20
Delivery photo attached to a fulfillment               15
Tracking number or signed confirmation (recipient)     10
Customer has 3+ earlier payments (not a shared email)  10

70 and above is well_defended, below 40 vulnerable, moderate in between.
"""

from dataclasses import dataclass
from uuid import UUID

from app.api.models.enums import ReconciliationStatus
from app.api.models.transactions import Transaction
from app.api.repo.readiness import ReadinessRepository
from app.api.schemas.readiness import (
    Readiness,
    ReadinessComponent,
    ReadinessDetail,
    ReadinessLabel,
)

WELL_DEFENDED_FROM: int = 70
VULNERABLE_BELOW: int = 40
REPEAT_CUSTOMER_PAYMENTS: int = 3

MATCHED: tuple[ReconciliationStatus, ...] = (
    ReconciliationStatus.AUTO_MATCHED,
    ReconciliationStatus.MANUALLY_MATCHED,
)

# key, label, points, what to do when missing
COMPONENTS: tuple[tuple[str, str, int, str], ...] = (
    ("transaction_record", "Payment confirmation", 20, ""),
    ("linked_order", "Linked order", 15, "Match the payment to its order."),
    (
        "customer_record",
        "Customer contact",
        10,
        "Add the customer's email or phone to their record.",
    ),
    ("fulfillment", "Fulfillment record", 20, "Log the delivery or service for this order."),
    ("delivery_photo", "Delivery photo", 15, "Attach a photo of the delivery."),
    (
        "tracking_or_signature",
        "Tracking number or signed confirmation",
        10,
        "Add the tracking number or who received it.",
    ),
    (
        "repeat_customer",
        "Repeat customer",
        10,
        f"Builds up once the customer has {REPEAT_CUSTOMER_PAYMENTS} earlier payments.",
    ),
)


@dataclass(frozen=True)
class ReadinessFacts:
    linked_order: bool
    customer_record: bool
    fulfillment: bool
    delivery_photo: bool
    tracking_or_signature: bool
    repeat_customer: bool


def label_for(score: int) -> ReadinessLabel:
    if score >= WELL_DEFENDED_FROM:
        return "well_defended"
    if score < VULNERABLE_BELOW:
        return "vulnerable"
    return "moderate"


def score_readiness(facts: ReadinessFacts) -> ReadinessDetail:
    available: dict[str, bool] = {
        "transaction_record": True,
        "linked_order": facts.linked_order,
        "customer_record": facts.customer_record,
        "fulfillment": facts.fulfillment,
        "delivery_photo": facts.delivery_photo,
        "tracking_or_signature": facts.tracking_or_signature,
        "repeat_customer": facts.repeat_customer,
    }
    components: list[ReadinessComponent] = [
        ReadinessComponent(
            key=key,
            label=label,
            status="available" if available[key] else "missing",
            points=points if available[key] else 0,
            max_points=points,
            suggestion=None if available[key] else suggestion,
        )
        for key, label, points, suggestion in COMPONENTS
    ]
    score: int = sum(component.points for component in components)
    return ReadinessDetail(score=score, label=label_for(score), components=components)


async def readiness_for(
    repo: ReadinessRepository, transactions: list[Transaction]
) -> dict[UUID, ReadinessDetail]:
    """Scores for the matched payments among transactions, keyed by id"""
    ids: list[UUID] = [
        t.id for t in transactions if t.order_id and t.reconciliation_status in MATCHED
    ]
    if not ids:
        return {}

    facts = await repo.evidence(ids, REPEAT_CUSTOMER_PAYMENTS)
    return {
        transaction_id: score_readiness(ReadinessFacts(*values))
        for transaction_id, values in facts.items()
    }


def summary(detail: ReadinessDetail | None) -> Readiness | None:
    """The score and label without the checklist, for lists"""
    return Readiness(score=detail.score, label=detail.label) if detail else None
