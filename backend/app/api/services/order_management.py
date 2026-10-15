from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk.logger as sentry_logger

from app.api.models.customers import Customer
from app.api.models.enums import OrderStatus
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.repo.customers import CustomerRepository
from app.api.repo.fulfillments import FulfillmentRepository
from app.api.repo.orders import OrderRepository
from app.api.repo.transactions import TransactionRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.customers import CustomerInDB, CustomerRef
from app.api.schemas.fulfillments import FulfillmentSummary
from app.api.schemas.orders import (
    OrderCreate,
    OrderDetail,
    OrderInDB,
    OrderListQuery,
    OrderResponse,
    OrderUpdate,
)
from app.api.schemas.pagination import PageMeta
from app.api.schemas.transactions import TransactionSummary
from app.api.services.customers import CustomerService, is_merchant_email
from app.api.services.orders import OrderService
from app.core.exceptions import (
    NotFoundError,
    OrderLinkedError,
    OrderStatusTransitionError,
)

# a linked order is the other half of a reconciliation match; changing these would
# invalidate the match, so the merchant unlinks it in reconciliation first
LINKED_LOCKED_FIELDS: tuple[str, ...] = ("order_number", "amount", "currency", "customer_id")

# paid is only set by reconciliation (a matched payment, or marking an order as cash)
MERCHANT_STATUS_TRANSITIONS: set[tuple[OrderStatus, OrderStatus]] = {
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.PAID, OrderStatus.FULFILLED),
}


def order_response(order: Order, customer: Customer | None, is_linked: bool) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        order_number=order.order_number,
        customer=CustomerRef.model_validate(customer) if customer else None,
        description=order.description,
        amount=order.amount,
        currency=order.currency,
        status=order.status,
        source=order.source,
        is_linked=is_linked,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


class OrderManagementService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_orders(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        self._order_repo = self._uow.repo(OrderRepository)
        self._order_service = OrderService(order_repo=self._order_repo)

        self._customer_service = CustomerService(customer_repo=self._uow.repo(CustomerRepository))

    async def _get_order(
        self, merchant_id: UUID, order_id: UUID, for_update: bool = False
    ) -> tuple[Order, Customer | None, bool]:
        """The order with its customer and link state"""
        # other merchants' orders are reported as missing, so existence is not revealed
        found: (
            tuple[Order, Customer | None, bool] | None
        ) = await self._order_repo.get_with_customer(merchant_id, order_id, for_update=for_update)

        if not found:
            raise NotFoundError("Order")

        return found

    async def _get_customer(self, merchant_id: UUID, customer_id: UUID | None) -> Customer | None:
        if not customer_id:
            return None

        customer: Customer | None = await self._customer_service._get_customer(
            id=customer_id, merchant_id=merchant_id
        )

        if not customer:
            raise NotFoundError("Customer")

        return customer

    async def list_orders(
        self, curr_merchant: Merchant, query: OrderListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[OrderResponse], PageMeta]:
        await self._uow_orders(uow)

        rows, total = await self._order_repo.list_orders(curr_merchant.id, query)

        orders: list[OrderResponse] = [
            order_response(order, customer, is_linked) for order, customer, is_linked in rows
        ]
        return orders, PageMeta.build(query, total)

    async def get_order(
        self, curr_merchant: Merchant, order_id: UUID, uow: UnitOfWorkRepository
    ) -> OrderDetail:
        await self._uow_orders(uow)

        merchant_id: UUID = curr_merchant.id

        order, customer, is_linked = await self._get_order(merchant_id, order_id)

        # separate queries: joining two one-to-many tables would multiply their rows
        transactions = await self._uow.repo(TransactionRepository).list_for_order(
            merchant_id, order.id
        )
        fulfillments = await self._uow.repo(FulfillmentRepository).list_for_order(
            merchant_id, order.id
        )

        return OrderDetail(
            **order_response(order, customer, is_linked).model_dump(),
            transactions=[TransactionSummary.model_validate(t) for t in transactions],
            fulfillments=[FulfillmentSummary.model_validate(f) for f in fulfillments],
        )

    async def create_order(
        self, curr_merchant: Merchant, payload: OrderCreate, uow: UnitOfWorkRepository
    ) -> OrderResponse:
        await self._uow_orders(uow)

        merchant_id: UUID = curr_merchant.id

        customer: Customer | None = await self._get_customer(merchant_id, payload.customer_id)

        if payload.customer_email:
            # links to the merchant's customer with this email, or creates them
            customer = await self._customer_service.get_or_create_customer(
                CustomerInDB(
                    merchant_id=merchant_id,
                    email=payload.customer_email,
                    is_shared=is_merchant_email(curr_merchant, payload.customer_email),
                )
            )

        order: Order = await self._order_service.create_order(
            OrderInDB(
                merchant_id=merchant_id,
                customer_id=customer.id if customer else None,
                order_number=payload.order_number,
                description=payload.description,
                amount=payload.amount,
                currency=payload.currency,
                source=payload.source,
            ),
            commit=True,
        )

        sentry_logger.info(
            "Merchant {merchant_id} created order {order_id}",
            merchant_id=str(merchant_id),
            order_id=str(order.id),
        )

        return order_response(order, customer, False)

    async def update_order(
        self,
        curr_merchant: Merchant,
        order_id: UUID,
        payload: OrderUpdate,
        uow: UnitOfWorkRepository,
    ) -> OrderResponse:
        await self._uow_orders(uow)

        merchant_id: UUID = curr_merchant.id
        changes: dict = payload.model_dump(exclude_unset=True)

        order, customer, is_linked = await self._get_order(merchant_id, order_id, for_update=True)

        # only fields whose value actually changes count, so resending the order is harmless
        changes = {
            field: value for field, value in changes.items() if getattr(order, field) != value
        }

        locked: list[str] = [field for field in LINKED_LOCKED_FIELDS if field in changes]
        if is_linked and locked:
            raise OrderLinkedError(locked)

        if "status" in changes and (order.status, changes["status"]) not in (
            MERCHANT_STATUS_TRANSITIONS
        ):
            raise OrderStatusTransitionError(order.status, changes["status"])

        # only a different customer needs looking up (and checking it is the merchant's)
        if "customer_id" in changes:
            customer = await self._get_customer(merchant_id, changes["customer_id"])

        if changes:
            for field, value in changes.items():
                setattr(order, field, value)
            order.updated_at = datetime.now(UTC)

            order = await self._order_service.update_order(order, commit=True)

        sentry_logger.info(
            "Merchant {merchant_id} updated order {order_id}",
            merchant_id=str(merchant_id),
            order_id=str(order_id),
        )

        return order_response(order, customer, is_linked)

    async def cancel_order(
        self, curr_merchant: Merchant, order_id: UUID, uow: UnitOfWorkRepository
    ) -> OrderResponse:
        """Soft delete: the order stays as a record with status cancelled"""
        await self._uow_orders(uow)

        merchant_id: UUID = curr_merchant.id

        order, customer, is_linked = await self._get_order(merchant_id, order_id, for_update=True)

        if order.status == OrderStatus.CANCELLED:
            return order_response(order, customer, is_linked)

        if is_linked:
            raise OrderLinkedError(["status"])

        if (order.status, OrderStatus.CANCELLED) not in MERCHANT_STATUS_TRANSITIONS:
            raise OrderStatusTransitionError(order.status, OrderStatus.CANCELLED)

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(UTC)
        order = await self._order_service.update_order(order, commit=True)

        sentry_logger.info(
            "Merchant {merchant_id} cancelled order {order_id}",
            merchant_id=str(merchant_id),
            order_id=str(order_id),
        )

        return order_response(order, customer, False)
