from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from app.api.models.customers import Customer
from app.api.models.merchants import Merchant
from app.api.repo.customers import CustomerRepository
from app.api.repo.orders import OrderRepository
from app.api.repo.transactions import TransactionRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.customers import (
    CustomerCreate,
    CustomerInDB,
    CustomerListQuery,
    CustomerResponse,
    CustomerStats,
    CustomerSummary,
    CustomerUpdate,
)
from app.api.schemas.orders import OrderListQuery, OrderResponse
from app.api.schemas.pagination import PageMeta, PageParams
from app.api.schemas.transactions import TransactionSummary
from app.api.services.customers import CustomerService, is_merchant_email
from app.api.services.order_management import order_response
from app.core.exceptions import CustomerEmailLockedError, CustomerExistsError, NotFoundError

EMPTY_STATS: dict = {
    "transaction_count": 0,
    "payment_count": 0,
    "reconciled_count": 0,
    "fulfilled_count": 0,
    "first_payment_at": None,
    "last_payment_at": None,
    "dispute_count": 0,
    "order_count": 0,
}


def _percent(part: int, whole: int, digits: int | None = None) -> float | int | None:
    if not whole:
        return None
    return round(part * 100 / whole, digits)


def _customer_stats(stats: dict) -> CustomerStats:
    # transaction_count (any status) is internal: it only decides whether the email is locked
    public: dict = {key: value for key, value in stats.items() if key != "transaction_count"}
    return CustomerStats(
        **public,
        reconciled_pct=_percent(stats["reconciled_count"], stats["payment_count"]),
        dispute_rate=_percent(stats["dispute_count"], stats["payment_count"], 1),
    )


def _customer_response(customer: Customer, stats: dict) -> CustomerResponse:
    return CustomerResponse(
        id=customer.id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        paystack_customer_code=customer.paystack_customer_code,
        is_shared=customer.is_shared,
        first_seen_at=customer.first_seen_at,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        stats=_customer_stats(stats),
    )


class CustomerLedgerService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_customers(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        self._customer_repo = self._uow.repo(CustomerRepository)
        self._customer_service = CustomerService(customer_repo=self._customer_repo)

    async def _get_customer(
        self, merchant_id: UUID, customer_id: UUID, for_update: bool = False
    ) -> Customer:
        # other merchants' customers are reported as missing, so existence is not revealed
        customer: Customer | None = await self._customer_service._get_customer(
            for_update=for_update, id=customer_id, merchant_id=merchant_id
        )

        if not customer:
            raise NotFoundError("Customer")

        return customer

    async def _raise_email_taken(self, merchant_id: UUID, email: str, exc: Exception = None):
        existing: Customer | None = await self._customer_service._get_customer(
            merchant_id=merchant_id, email=email
        )
        raise CustomerExistsError(str(existing.id) if existing else "") from exc

    async def list_customers(
        self, curr_merchant: Merchant, query: CustomerListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[CustomerSummary], PageMeta]:
        await self._uow_customers(uow)

        rows, total = await self._customer_repo.list_customers(curr_merchant.id, query)

        customers: list[CustomerSummary] = [
            CustomerSummary(
                id=row["customer"].id,
                name=row["customer"].name,
                email=row["customer"].email,
                phone=row["customer"].phone,
                is_shared=row["customer"].is_shared,
                payment_count=row["payment_count"],
                reconciled_pct=_percent(row["reconciled_count"], row["payment_count"]),
                dispute_count=row["dispute_count"],
                last_payment_at=row["last_payment_at"],
                first_seen_at=row["customer"].first_seen_at,
                created_at=row["customer"].created_at,
            )
            for row in rows
        ]

        return customers, PageMeta.build(query, total)

    async def _get_customer_with_stats(
        self, merchant_id: UUID, customer_id: UUID, for_update: bool = False
    ) -> tuple[Customer, dict]:
        found: tuple[Customer, dict] | None = await self._customer_repo.get_with_stats(
            merchant_id, customer_id, for_update=for_update
        )

        if not found:
            raise NotFoundError("Customer")

        return found

    async def get_customer(
        self, curr_merchant: Merchant, customer_id: UUID, uow: UnitOfWorkRepository
    ) -> CustomerResponse:
        await self._uow_customers(uow)

        customer, stats = await self._get_customer_with_stats(curr_merchant.id, customer_id)

        return _customer_response(customer, stats)

    async def create_customer(
        self, curr_merchant: Merchant, payload: CustomerCreate, uow: UnitOfWorkRepository
    ) -> CustomerResponse:
        await self._uow_customers(uow)

        merchant_id: UUID = curr_merchant.id

        try:
            customer: Customer = await self._customer_service.create_customer(
                CustomerInDB(
                    merchant_id=merchant_id,
                    name=payload.name,
                    email=payload.email,
                    phone=payload.phone,
                    is_shared=is_merchant_email(curr_merchant, payload.email),
                ),
                commit=True,
            )
        except IntegrityError as exc:
            # the unique (merchant, email) constraint is the check, including concurrent creates
            await self._raise_email_taken(merchant_id, payload.email, exc)

        sentry_logger.info(
            "Merchant {merchant_id} created customer {customer_id}",
            merchant_id=str(merchant_id),
            customer_id=str(customer.id),
        )

        # a new customer has no payments, orders or disputes yet
        return _customer_response(customer, EMPTY_STATS)

    async def update_customer(
        self,
        curr_merchant: Merchant,
        customer_id: UUID,
        payload: CustomerUpdate,
        uow: UnitOfWorkRepository,
    ) -> CustomerResponse:
        await self._uow_customers(uow)

        merchant_id: UUID = curr_merchant.id
        changes: dict = payload.model_dump(exclude_unset=True)

        # contact fields do not affect the stats, so the ones read here are returned as they are
        customer, stats = await self._get_customer_with_stats(
            merchant_id, customer_id, for_update=True
        )

        email_changed: bool = "email" in changes and changes["email"] != customer.email

        if email_changed:
            # synced payments are tied to the customer by email
            if stats["transaction_count"]:
                raise CustomerEmailLockedError()

            if changes["email"]:
                existing: Customer | None = await self._customer_service._get_customer(
                    merchant_id=merchant_id, email=changes["email"]
                )
                if existing and existing.id != customer.id:
                    raise CustomerExistsError(str(existing.id))

        name: str | None = changes.get("name", customer.name)
        email: str | None = changes.get("email", customer.email)
        if not name and not email:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "name"),
                        "msg": "name or email is required",
                        "type": "value_error",
                    }
                ]
            )

        if changes:
            for field, value in changes.items():
                setattr(customer, field, value)

            # a new email that is the merchant's own is shared unless the merchant says otherwise
            if email_changed and "is_shared" not in changes:
                customer.is_shared = is_merchant_email(curr_merchant, email)

            customer.updated_at = datetime.now(UTC)

            try:
                customer = await self._customer_service.update_customer(customer, commit=True)
            except IntegrityError as exc:
                await self._raise_email_taken(merchant_id, email, exc)

        sentry_logger.info(
            "Merchant {merchant_id} updated customer {customer_id}",
            merchant_id=str(merchant_id),
            customer_id=str(customer_id),
        )

        return _customer_response(customer, stats)

    async def list_customer_transactions(
        self,
        curr_merchant: Merchant,
        customer_id: UUID,
        params: PageParams,
        uow: UnitOfWorkRepository,
    ) -> tuple[list[TransactionSummary], PageMeta]:
        await self._uow_customers(uow)

        customer: Customer = await self._get_customer(curr_merchant.id, customer_id)

        transaction_repo: TransactionRepository = self._uow.repo(TransactionRepository)
        rows, total = await transaction_repo.list_for_customer(
            curr_merchant.id, customer.id, params
        )

        transactions: list[TransactionSummary] = [
            TransactionSummary.model_validate(row) for row in rows
        ]
        return transactions, PageMeta.build(params, total)

    async def list_customer_orders(
        self,
        curr_merchant: Merchant,
        customer_id: UUID,
        params: PageParams,
        uow: UnitOfWorkRepository,
    ) -> tuple[list[OrderResponse], PageMeta]:
        await self._uow_customers(uow)

        customer: Customer = await self._get_customer(curr_merchant.id, customer_id)

        order_repo: OrderRepository = self._uow.repo(OrderRepository)
        query = OrderListQuery(page=params.page, limit=params.limit, customer_id=customer.id)
        rows, total = await order_repo.list_orders(curr_merchant.id, query)

        orders: list[OrderResponse] = [
            order_response(order, order_customer, is_linked)
            for order, order_customer, is_linked in rows
        ]
        return orders, PageMeta.build(params, total)
