"""The reconciliation tiers, as pure rules over already loaded rows.

Used by the automatic pass after every sync (celery) and by reconciliation sessions (api);
reconciliation_engine loads the rows and writes the plan.

Tier 1, order number: the order number is the payment's reference, or its metadata
order_number / order_id (top level or a custom field). Same amount: matched (100), or
suggested when the merchant turned auto-confirm off. Different amount: the payment is
flagged amount_mismatch.
Tier 2, customer + amount: the payment's customer (not a shared email) placed an order for
the same amount up to 7 days before paying. One such order: matched (95); several: each is
suggested (80).
Tier 3, amount + time: exactly one order for the same amount within 24 hours of the payment,
either side. Suggested (90).

Orders are only candidates while pending, unlinked, unresolved and unflagged, and in the
payment's currency. A pair the merchant rejected is never matched or suggested again.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

TIER2_WINDOW = timedelta(days=7)
TIER3_WINDOW = timedelta(hours=24)

TIER1_CONFIDENCE: int = 100
TIER2_CONFIDENCE: int = 95
TIER2_SEVERAL_CONFIDENCE: int = 80
TIER3_CONFIDENCE: int = 90

AMOUNT_MISMATCH: str = "amount_mismatch"

# metadata keys (and custom field variable names) that can carry the order number
ORDER_NUMBER_KEYS: tuple[str, ...] = ("order_number", "order_id", "order_no", "order")


@dataclass(frozen=True)
class Payment:
    id: UUID
    reference: str
    amount: int
    currency: str
    paid_at: datetime
    metadata: Any
    customer_id: UUID | None
    customer_shared: bool


@dataclass(frozen=True)
class Candidate:
    id: UUID
    order_number: str | None
    amount: int
    currency: str
    customer_id: UUID | None
    ordered_at: datetime


@dataclass(frozen=True)
class Match:
    transaction_id: UUID
    order_id: UUID
    tier: int
    confidence: int


@dataclass(frozen=True)
class Suggestion:
    transaction_id: UUID
    order_id: UUID
    tier: int
    confidence: int
    reason: str


@dataclass(frozen=True)
class Flag:
    transaction_id: UUID
    reason: str


@dataclass
class MatchPlan:
    matches: list[Match] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)


def _normalise(value: Any) -> str | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = str(int(value)) if float(value).is_integer() else str(value)
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value or None


def order_number_keys(payment: Payment) -> list[str]:
    """Every value in the payment that could be an order number, normalised"""
    values: list[Any] = [payment.reference]
    metadata = payment.metadata

    if isinstance(metadata, dict):
        values.extend(metadata.get(key) for key in ORDER_NUMBER_KEYS)
        custom_fields = metadata.get("custom_fields")
        if isinstance(custom_fields, list):
            for custom_field in custom_fields:
                if not isinstance(custom_field, dict):
                    continue
                name: str | None = _normalise(custom_field.get("variable_name"))
                if name in ORDER_NUMBER_KEYS:
                    values.append(custom_field.get("value"))

    keys: list[str] = []
    for value in values:
        key: str | None = _normalise(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def _hours_between(earlier: datetime, later: datetime) -> str:
    hours: float = abs((later - earlier).total_seconds()) / 3600
    if hours < 1:
        return "less than an hour"
    rounded: int = round(hours)
    return f"{rounded} hour{'s' if rounded != 1 else ''}"


def _timing(payment: Payment, order: Candidate) -> str:
    if payment.paid_at >= order.ordered_at:
        return f"paid {_hours_between(order.ordered_at, payment.paid_at)} after the order"
    return f"paid {_hours_between(payment.paid_at, order.ordered_at)} before the order was placed"


def plan_matches(
    payments: list[Payment],
    orders: list[Candidate],
    rejected: set[tuple[UUID, UUID]],
    tier1_auto: bool = True,
) -> MatchPlan:
    """Which payments to link, suggest or flag. An order is linked to at most one payment;
    earlier payments go first, and every tier 1 match before any tier 2 one"""
    plan = MatchPlan()
    payments = sorted(payments, key=lambda p: (p.paid_at, str(p.id)))
    open_orders: dict[UUID, Candidate] = {order.id: order for order in orders}
    by_number: dict[str, list[Candidate]] = {}
    for order in orders:
        key: str | None = _normalise(order.order_number)
        if key:
            by_number.setdefault(key, []).append(order)

    # payments tier 1 settled (matched, suggested or flagged): later tiers skip them
    settled: set[UUID] = set()

    def available(order: Candidate, payment: Payment) -> bool:
        return order.id in open_orders and (payment.id, order.id) not in rejected

    def link(payment: Payment, order: Candidate, tier: int, confidence: int):
        plan.matches.append(Match(payment.id, order.id, tier, confidence))
        del open_orders[order.id]
        settled.add(payment.id)

    # tier 1: order number
    for payment in payments:
        for key in order_number_keys(payment):
            found: list[Candidate] = [
                order
                for order in by_number.get(key, [])
                if available(order, payment) and order.currency == payment.currency
            ]
            if not found:
                continue
            order = found[0]
            if order.amount != payment.amount:
                plan.flags.append(Flag(payment.id, AMOUNT_MISMATCH))
                settled.add(payment.id)
            elif tier1_auto:
                link(payment, order, 1, TIER1_CONFIDENCE)
            else:
                plan.suggestions.append(
                    Suggestion(
                        payment.id,
                        order.id,
                        1,
                        TIER1_CONFIDENCE,
                        f"Order number {order.order_number} is on the payment, amount identical.",
                    )
                )
                settled.add(payment.id)
            break

    # tier 2: the same customer, the same amount, ordered in the 7 days before paying
    for payment in payments:
        if payment.id in settled or not payment.customer_id or payment.customer_shared:
            continue
        found = [
            order
            for order in open_orders.values()
            if available(order, payment)
            and order.customer_id == payment.customer_id
            and order.amount == payment.amount
            and order.currency == payment.currency
            and payment.paid_at - TIER2_WINDOW <= order.ordered_at <= payment.paid_at
        ]
        if len(found) == 1:
            link(payment, found[0], 2, TIER2_CONFIDENCE)
        elif found:
            for order in found:
                plan.suggestions.append(
                    Suggestion(
                        payment.id,
                        order.id,
                        2,
                        TIER2_SEVERAL_CONFIDENCE,
                        f"Amount identical, {_timing(payment, order)}, same customer email; "
                        f"{len(found)} orders qualify.",
                    )
                )
            settled.add(payment.id)

    # tier 3: the same amount within 24 hours, when only one order qualifies
    for payment in payments:
        if payment.id in settled:
            continue
        found = [
            order
            for order in open_orders.values()
            if available(order, payment)
            and order.amount == payment.amount
            and order.currency == payment.currency
            and abs(payment.paid_at - order.ordered_at) <= TIER3_WINDOW
        ]
        if len(found) == 1:
            order = found[0]
            plan.suggestions.append(
                Suggestion(
                    payment.id,
                    order.id,
                    3,
                    TIER3_CONFIDENCE,
                    f"Amount identical, {_timing(payment, order)}.",
                )
            )

    # an order linked later in the pass is no longer a suggestion for anyone
    plan.suggestions = [s for s in plan.suggestions if s.order_id in open_orders]
    return plan
