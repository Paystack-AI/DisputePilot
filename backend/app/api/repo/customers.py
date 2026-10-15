from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import ReconciliationStatus, TransactionStatus
from app.api.models.fulfillments import Fulfillment
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.base import LIKE_ESCAPE, BaseRepository, contains_pattern
from app.api.schemas.customers import CustomerInDB, CustomerListQuery

_SUCCESS = Transaction.status == TransactionStatus.SUCCESS
_RECONCILED = Transaction.reconciliation_status.in_(
    (ReconciliationStatus.AUTO_MATCHED, ReconciliationStatus.MANUALLY_MATCHED)
)


class CustomerRepository(BaseRepository[CustomerInDB, Customer]):
    model = Customer

    @staticmethod
    def _entity_to_model(entity: CustomerInDB) -> model:
        return Customer(**entity.model_dump())

    def _get_filters(self, **filters) -> list[Any]:
        filter_conditions = []

        if "id" in filters:
            filter_conditions.append(self.model.id == filters["id"])
        if "merchant_id" in filters:
            filter_conditions.append(self.model.merchant_id == filters["merchant_id"])
        if "email" in filters:
            filter_conditions.append(self.model.email == filters["email"])
        if "paystack_customer_code" in filters:
            filter_conditions.append(
                self.model.paystack_customer_code == filters["paystack_customer_code"]
            )

        return filter_conditions

    async def get_or_create_by_email(self, customer: CustomerInDB) -> Customer:
        """Customer for the merchant and email, created when missing. Safe under concurrent
        syncs and order creation: an existing row is left untouched"""
        await self._async_session.execute(
            insert(self.model)
            .values(**customer.model_dump())
            .on_conflict_do_nothing(constraint="customers_merchant_email_uq")
        )

        return await self.get_record(merchant_id=customer.merchant_id, email=customer.email)

    @staticmethod
    def _payments_subquery(merchant_id: UUID):
        return (
            select(
                Transaction.customer_id.label("customer_id"),
                func.count().filter(_SUCCESS).label("payment_count"),
                func.count().filter(and_(_SUCCESS, _RECONCILED)).label("reconciled_count"),
                func.min(Transaction.paid_at).filter(_SUCCESS).label("first_payment_at"),
                func.max(Transaction.paid_at).filter(_SUCCESS).label("last_payment_at"),
            )
            .where(Transaction.merchant_id == merchant_id, Transaction.customer_id.is_not(None))
            .group_by(Transaction.customer_id)
            .subquery("payments")
        )

    @staticmethod
    def _disputes_subquery(merchant_id: UUID):
        return (
            select(
                Transaction.customer_id.label("customer_id"),
                func.count(Dispute.id).label("dispute_count"),
            )
            .join(Transaction, Dispute.transaction_id == Transaction.id)
            .where(Dispute.merchant_id == merchant_id, Transaction.customer_id.is_not(None))
            .group_by(Transaction.customer_id)
            .subquery("disputes")
        )

    def _list_filters(self, merchant_id: UUID, query: CustomerListQuery) -> list[Any]:
        conditions: list[Any] = [self.model.merchant_id == merchant_id]

        if query.search:
            pattern: str = contains_pattern(query.search)
            conditions.append(
                or_(
                    self.model.name.ilike(pattern, escape=LIKE_ESCAPE),
                    self.model.email.ilike(pattern, escape=LIKE_ESCAPE),
                )
            )
        if query.is_shared is not None:
            conditions.append(self.model.is_shared == query.is_shared)

        return conditions

    async def list_customers(
        self, merchant_id: UUID, query: CustomerListQuery
    ) -> tuple[list[dict], int]:
        """Page of customers with their ledger counts, and the total matching the filters"""
        conditions: list[Any] = self._list_filters(merchant_id, query)

        total: int = await self._async_session.scalar(
            select(func.count(self.model.id)).where(*conditions)
        )

        payments = self._payments_subquery(merchant_id)
        disputes = self._disputes_subquery(merchant_id)

        payment_count = func.coalesce(payments.c.payment_count, 0).label("payment_count")
        reconciled_count = func.coalesce(payments.c.reconciled_count, 0).label("reconciled_count")
        dispute_count = func.coalesce(disputes.c.dispute_count, 0).label("dispute_count")
        last_payment_at = payments.c.last_payment_at.label("last_payment_at")

        sort_columns: dict[str, Any] = {
            "name": self.model.name,
            "email": self.model.email,
            "payment_count": payment_count,
            "dispute_count": dispute_count,
            "last_payment_at": last_payment_at,
            "created_at": self.model.created_at,
        }
        descending: bool = query.sort.startswith("-")
        sort_column = sort_columns.get(query.sort.lstrip("-"), self.model.created_at)

        # id breaks ties so pages never repeat or skip rows
        order_by = (
            (sort_column.desc().nulls_last(), self.model.id.desc())
            if descending
            else (sort_column.asc().nulls_last(), self.model.id.asc())
        )

        stmt: Select = (
            select(self.model, payment_count, reconciled_count, dispute_count, last_payment_at)
            .outerjoin(payments, payments.c.customer_id == self.model.id)
            .outerjoin(disputes, disputes.c.customer_id == self.model.id)
            .where(*conditions)
            .order_by(*order_by)
            .offset(query.offset)
            .limit(query.limit)
        )

        rows = (await self._async_session.execute(stmt)).all()

        return [
            {
                "customer": row[0],
                "payment_count": row.payment_count,
                "reconciled_count": row.reconciled_count,
                "dispute_count": row.dispute_count,
                "last_payment_at": row.last_payment_at,
            }
            for row in rows
        ], total

    async def get_with_stats(
        self, merchant_id: UUID, customer_id: UUID, for_update: bool = False
    ) -> tuple[Customer, dict] | None:
        """The merchant's customer and their ledger counts in one query. for_update locks
        only the customer row"""
        # one aggregate row for the customer's payments, joined onto the customer
        payments = (
            select(
                func.count().label("transaction_count"),  # any status; locks the email
                func.count().filter(_SUCCESS).label("payment_count"),
                func.count().filter(and_(_SUCCESS, _RECONCILED)).label("reconciled_count"),
                func.count()
                .filter(_SUCCESS, exists().where(Fulfillment.order_id == Transaction.order_id))
                .label("fulfilled_count"),
                func.min(Transaction.paid_at).filter(_SUCCESS).label("first_payment_at"),
                func.max(Transaction.paid_at).filter(_SUCCESS).label("last_payment_at"),
            )
            .where(Transaction.merchant_id == merchant_id, Transaction.customer_id == customer_id)
            .subquery("payments")
        )
        dispute_count = (
            select(func.count(Dispute.id))
            .join(Transaction, Dispute.transaction_id == Transaction.id)
            .where(Dispute.merchant_id == merchant_id, Transaction.customer_id == customer_id)
            .scalar_subquery()
            .label("dispute_count")
        )
        order_count = (
            select(func.count(Order.id))
            .where(Order.merchant_id == merchant_id, Order.customer_id == customer_id)
            .scalar_subquery()
            .label("order_count")
        )

        stmt: Select = (
            select(self.model, payments, dispute_count, order_count)
            .join(payments, true())
            .where(self.model.id == customer_id, self.model.merchant_id == merchant_id)
        )
        if for_update:
            stmt = stmt.with_for_update(of=self.model)

        row = (await self._async_session.execute(stmt)).one_or_none()
        if row is None:
            return None

        return row[0], {
            "transaction_count": row.transaction_count,
            "payment_count": row.payment_count,
            "reconciled_count": row.reconciled_count,
            "fulfilled_count": row.fulfilled_count,
            "first_payment_at": row.first_payment_at,
            "last_payment_at": row.last_payment_at,
            "dispute_count": row.dispute_count,
            "order_count": row.order_count,
        }
