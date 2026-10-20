from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.api.services.matching import (
    AMOUNT_MISMATCH,
    Candidate,
    Payment,
    order_number_keys,
    plan_matches,
)

NOW: datetime = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
ADA: UUID = uuid4()


def _payment(**fields) -> Payment:
    values: dict = {
        "id": uuid4(),
        "reference": f"T{uuid4().hex[:8]}",
        "amount": 4500000,
        "currency": "NGN",
        "paid_at": NOW,
        "metadata": None,
        "customer_id": None,
        "customer_shared": False,
    }
    values.update(fields)
    return Payment(**values)


def _order(**fields) -> Candidate:
    values: dict = {
        "id": uuid4(),
        "order_number": None,
        "amount": 4500000,
        "currency": "NGN",
        "customer_id": None,
        "created_at": NOW - timedelta(hours=3),
    }
    values.update(fields)
    return Candidate(**values)


class TestOrderNumberKeys:
    def test_reference_metadata_and_custom_fields(self):
        payment = _payment(
            reference="REF-1",
            metadata={
                "order_number": " A-1032 ",
                "order_id": 1033,
                "custom_fields": [
                    {"variable_name": "Order_No", "value": "X9"},
                    {"variable_name": "colour", "value": "red"},
                    "junk",
                ],
            },
        )
        assert order_number_keys(payment) == ["ref-1", "a-1032", "1033", "x9"]

    def test_metadata_that_is_not_an_object(self):
        assert order_number_keys(_payment(reference="R", metadata="1032")) == ["r"]


class TestTier1:
    def test_order_number_matches(self):
        order = _order(order_number="A-1032", created_at=NOW - timedelta(days=20))
        payment = _payment(metadata={"order_number": "a-1032"})

        plan = plan_matches([payment], [order], set())

        assert [(m.order_id, m.tier, m.confidence) for m in plan.matches] == [(order.id, 1, 100)]

    def test_reference_is_the_order_number(self):
        order = _order(order_number="1048")
        plan = plan_matches([_payment(reference="1048")], [order], set())
        assert plan.matches[0].order_id == order.id

    def test_different_amount_is_flagged(self):
        order = _order(order_number="A-1", amount=4000000)
        payment = _payment(reference="A-1")

        plan = plan_matches([payment], [order], set())

        assert not plan.matches and not plan.suggestions
        assert [(f.transaction_id, f.reason) for f in plan.flags] == [(payment.id, AMOUNT_MISMATCH)]

    def test_auto_confirm_off_suggests(self):
        order = _order(order_number="A-1")
        plan = plan_matches([_payment(reference="A-1")], [order], set(), tier1_auto=False)

        assert not plan.matches
        assert [(s.order_id, s.tier, s.confidence) for s in plan.suggestions] == [
            (order.id, 1, 100)
        ]

    def test_other_currency_is_not_a_candidate(self):
        order = _order(order_number="A-1", currency="USD")
        plan = plan_matches([_payment(reference="A-1")], [order], set())
        assert not plan.matches and not plan.flags


class TestTier2:
    def test_one_order_from_the_customer_matches(self):
        order = _order(customer_id=ADA, created_at=NOW - timedelta(days=6))
        plan = plan_matches([_payment(customer_id=ADA)], [order], set())
        assert [(m.order_id, m.tier, m.confidence) for m in plan.matches] == [(order.id, 2, 95)]

    def test_several_orders_are_suggested(self):
        orders = [
            _order(customer_id=ADA),
            _order(customer_id=ADA, created_at=NOW - timedelta(days=2)),
        ]
        plan = plan_matches([_payment(customer_id=ADA)], orders, set())

        assert not plan.matches
        assert {s.order_id for s in plan.suggestions} == {o.id for o in orders}
        assert {s.tier for s in plan.suggestions} == {2}
        assert "2 orders qualify" in plan.suggestions[0].reason

    def test_shared_email_is_not_matched_by_customer(self):
        order = _order(customer_id=ADA, created_at=NOW - timedelta(days=3))
        plan = plan_matches([_payment(customer_id=ADA, customer_shared=True)], [order], set())
        assert not plan.matches and not plan.suggestions

    def test_older_than_7_days_is_not_matched(self):
        order = _order(customer_id=ADA, created_at=NOW - timedelta(days=8))
        plan = plan_matches([_payment(customer_id=ADA)], [order], set())
        assert not plan.matches


class TestTier3:
    def test_one_order_within_24_hours_is_suggested(self):
        order = _order()
        plan = plan_matches([_payment()], [order], set())

        assert not plan.matches
        suggestion = plan.suggestions[0]
        assert (suggestion.order_id, suggestion.tier, suggestion.confidence) == (order.id, 3, 90)
        assert suggestion.reason == "Amount identical, paid 3 hours after the order."

    def test_order_logged_after_the_payment(self):
        order = _order(created_at=NOW + timedelta(hours=2))
        plan = plan_matches([_payment()], [order], set())
        assert "before the order was logged" in plan.suggestions[0].reason

    def test_several_orders_suggest_nothing(self):
        plan = plan_matches([_payment()], [_order(), _order()], set())
        assert not plan.suggestions


class TestPlan:
    def test_rejected_pair_is_skipped(self):
        order = _order(order_number="A-1")
        payment = _payment(reference="A-1")
        plan = plan_matches([payment], [order], {(payment.id, order.id)})
        assert not plan.matches and not plan.suggestions

    def test_an_order_is_linked_once(self):
        order = _order(customer_id=ADA, created_at=NOW - timedelta(days=1))
        first = _payment(customer_id=ADA)
        second = _payment(customer_id=ADA, paid_at=NOW + timedelta(minutes=5))

        plan = plan_matches([second, first], [order], set())

        assert [m.transaction_id for m in plan.matches] == [first.id]

    def test_tier1_goes_before_tier2(self):
        order = _order(order_number="A-1", customer_id=ADA)
        by_customer = _payment(customer_id=ADA, paid_at=NOW - timedelta(minutes=5))
        by_number = _payment(reference="A-1")

        plan = plan_matches([by_customer, by_number], [order], set())

        assert [m.transaction_id for m in plan.matches] == [by_number.id]

    def test_suggestion_for_an_order_linked_later_is_dropped(self):
        order = _order(customer_id=ADA, created_at=NOW - timedelta(hours=2))
        stranger = _payment(paid_at=NOW - timedelta(hours=1))  # tier 3 for the order
        ada = _payment(customer_id=ADA)  # tier 2 takes it

        plan = plan_matches([stranger, ada], [order], set())

        assert [m.transaction_id for m in plan.matches] == [ada.id]
        assert not plan.suggestions
