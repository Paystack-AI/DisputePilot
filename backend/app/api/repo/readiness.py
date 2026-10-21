from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.models.customers import Customer
from app.api.models.enums import TransactionStatus
from app.api.models.files import StoredFile
from app.api.models.fulfillments import Fulfillment
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import BaseRepository


def _filled(column):
    return func.coalesce(func.trim(column), "") != ""


class ReadinessRepository(BaseRepository[BaseModel, Transaction]):
    """Read side only: the evidence dispute readiness is scored from"""

    model = Transaction

    @staticmethod
    def _entity_to_model(entity: BaseModel) -> model:
        return Transaction(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        return []

    @staticmethod
    def evidence_statement(transaction_ids, repeat_payments: int) -> Select:
        """Per payment: linked to an order, customer has an email or phone, fulfillment
        logged, delivery photo attached, tracking number or recipient recorded, repeat
        customer (repeat_payments earlier successful payments, not a shared email).
        transaction_ids is a list or a subquery of ids"""
        customer_id = func.coalesce(Transaction.customer_id, Order.customer_id)
        # recorded against the payment itself or against its order
        linked_fulfillment = and_(
            Fulfillment.merchant_id == Transaction.merchant_id,
            or_(
                Fulfillment.transaction_id == Transaction.id,
                Fulfillment.order_id == Transaction.order_id,
            ),
        )
        Earlier = aliased(Transaction)
        earlier_payments = (
            select(func.count(Earlier.id))
            .where(
                Earlier.merchant_id == Transaction.merchant_id,
                Earlier.customer_id == customer_id,
                Earlier.status == TransactionStatus.SUCCESS,
                Earlier.paid_at < Transaction.paid_at,
            )
            .scalar_subquery()
        )

        return (
            select(
                Transaction.id,
                Order.id.is_not(None),
                func.coalesce(_filled(Customer.email) | _filled(Customer.phone), False),
                exists().where(linked_fulfillment),
                exists().where(linked_fulfillment, StoredFile.fulfillment_id == Fulfillment.id),
                exists().where(
                    linked_fulfillment,
                    or_(_filled(Fulfillment.tracking_number), _filled(Fulfillment.recipient_name)),
                ),
                func.coalesce(~Customer.is_shared, False) & (earlier_payments >= repeat_payments),
            )
            .outerjoin(Order, Order.id == Transaction.order_id)
            .outerjoin(Customer, Customer.id == customer_id)
            .where(Transaction.id.in_(transaction_ids))
        )

    @staticmethod
    def to_facts(rows) -> dict[UUID, tuple[bool, ...]]:
        return {row[0]: tuple(bool(value) for value in row[1:]) for row in rows}

    async def evidence(
        self, transaction_ids: list[UUID], repeat_payments: int
    ) -> dict[UUID, tuple[bool, ...]]:
        """evidence_statement for these payments, in one query"""
        rows = await self._async_session.execute(
            self.evidence_statement(transaction_ids, repeat_payments)
        )
        return self.to_facts(rows.all())
