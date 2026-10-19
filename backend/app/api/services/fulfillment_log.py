from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from app.api.models.enums import OrderStatus
from app.api.models.files import StoredFile
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.repo.files import FileRepository
from app.api.repo.fulfillments import FulfillmentRepository
from app.api.repo.orders import OrderRepository
from app.api.repo.transactions import TransactionRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.files import FileResponse
from app.api.schemas.fulfillments import (
    FulfillmentCreate,
    FulfillmentInDB,
    FulfillmentListQuery,
    FulfillmentResponse,
    FulfillmentUpdate,
)
from app.api.schemas.pagination import PageMeta
from app.api.services.fulfillments import FulfillmentService
from app.core.exceptions import (
    FileAlreadyAttachedError,
    NotFoundError,
    OrderStatusTransitionError,
    ServerError,
)

DETAIL_FIELDS: tuple[str, ...] = (
    "type",
    "delivery_date",
    "tracking_number",
    "recipient_name",
    "delivery_address",
    "notes",
)


def fulfillment_response(fulfillment: Fulfillment, files: list[StoredFile]) -> FulfillmentResponse:
    return FulfillmentResponse(
        id=fulfillment.id,
        order_id=fulfillment.order_id,
        transaction_id=fulfillment.transaction_id,
        type=fulfillment.type,
        delivery_date=fulfillment.delivery_date,
        tracking_number=fulfillment.tracking_number,
        recipient_name=fulfillment.recipient_name,
        delivery_address=fulfillment.delivery_address,
        notes=fulfillment.notes,
        files=[FileResponse.model_validate(stored_file) for stored_file in files],
        created_at=fulfillment.created_at,
        updated_at=fulfillment.updated_at,
    )


class FulfillmentLogService:
    def __init__(self):
        self._uow = None

    async def _setup_uow(self, uow: UnitOfWorkRepository):
        self._uow = uow

    async def _uow_fulfillments(self, uow: UnitOfWorkRepository):
        await self._setup_uow(uow)

        self._fulfillment_repo = self._uow.repo(FulfillmentRepository)
        self._fulfillment_service = FulfillmentService(fulfillment_repo=self._fulfillment_repo)
        self._file_repo = self._uow.repo(FileRepository)

    async def _get_fulfillment(
        self, merchant_id: UUID, fulfillment_id: UUID, for_update: bool = False
    ) -> Fulfillment:
        # other merchants' records are reported as missing, so existence is not revealed
        fulfillment: Fulfillment | None = await self._fulfillment_service._get_fulfillment(
            for_update=for_update, id=fulfillment_id, merchant_id=merchant_id
        )
        if not fulfillment:
            raise NotFoundError("Fulfillment")
        return fulfillment

    async def _attach_files(
        self,
        merchant_id: UUID,
        fulfillment_id: UUID,
        file_ids: list[UUID],
        already_attached: set[UUID] = frozenset(),
    ):
        """Attaches the merchant's unattached uploads; locked so two requests can not claim
        the same file"""
        if not file_ids:
            return

        found: dict[UUID, StoredFile] = {
            stored_file.id: stored_file
            for stored_file in await self._file_repo.lock_for_merchant(merchant_id, file_ids)
        }

        for file_id in file_ids:
            stored_file: StoredFile | None = found.get(file_id)
            if stored_file is None:
                raise NotFoundError("File")
            if file_id in already_attached:
                continue
            if stored_file.fulfillment_id or stored_file.dispute_id:
                raise FileAlreadyAttachedError(str(file_id))
            stored_file.fulfillment_id = fulfillment_id

    async def _commit(self, message: str):
        try:
            await self._uow.commit()
        except Exception as exc:
            await self._uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(message)
            raise ServerError() from exc

    async def _replay(
        self, merchant_id: UUID, idempotency_key: str, order_id: UUID
    ) -> FulfillmentResponse | None:
        """The response for a create already made with this key, or None for a new key"""
        existing: Fulfillment | None = await self._fulfillment_service._get_fulfillment(
            merchant_id=merchant_id, idempotency_key=idempotency_key
        )
        if existing is None:
            return None

        # a reused key must be a retry of the same request, not a different delivery
        if existing.order_id != order_id:
            raise RequestValidationError(
                [
                    {
                        "loc": ("header", "Idempotency-Key"),
                        "msg": "this key was already used for a different order",
                        "type": "value_error",
                    }
                ]
            )

        sentry_logger.info(
            "Replayed fulfillment {fulfillment_id} for a retried create",
            fulfillment_id=str(existing.id),
        )
        return fulfillment_response(existing, await self._file_repo.for_fulfillment(existing.id))

    async def create_fulfillment(
        self,
        curr_merchant: Merchant,
        payload: FulfillmentCreate,
        uow: UnitOfWorkRepository,
        idempotency_key: str | None = None,
    ) -> FulfillmentResponse:
        """A retry with the same Idempotency-Key returns the first fulfillment instead of
        logging the delivery twice"""
        await self._uow_fulfillments(uow)

        merchant_id: UUID = curr_merchant.id

        # locked first: concurrent retries for the order wait here, then see the first
        # request's committed record below
        order: Order | None = await self._uow.repo(OrderRepository).get_record(
            for_update=True, id=payload.order_id, merchant_id=merchant_id
        )
        if not order:
            raise NotFoundError("Order")

        if idempotency_key:
            replayed: FulfillmentResponse | None = await self._replay(
                merchant_id, idempotency_key, order.id
            )
            if replayed is not None:
                return replayed

        if order.status == OrderStatus.CANCELLED:
            raise OrderStatusTransitionError(order.status, OrderStatus.FULFILLED)

        transaction_repo: TransactionRepository = self._uow.repo(TransactionRepository)
        transaction: Transaction | None
        if payload.transaction_id:
            transaction = await transaction_repo.get_record(
                id=payload.transaction_id, merchant_id=merchant_id
            )
            if not transaction:
                raise NotFoundError("Transaction")
            if transaction.order_id and transaction.order_id != order.id:
                raise RequestValidationError(
                    [
                        {
                            "loc": ("body", "transaction_id"),
                            "msg": "this payment is linked to a different order",
                            "type": "value_error",
                        }
                    ]
                )
        else:
            # the payment reconciliation linked to this order, if any
            transaction = await transaction_repo.get_record(
                order_id=order.id, merchant_id=merchant_id
            )

        try:
            fulfillment: Fulfillment = await self._fulfillment_service.create_fulfillment(
                FulfillmentInDB(
                    merchant_id=merchant_id,
                    order_id=order.id,
                    transaction_id=transaction.id if transaction else None,
                    idempotency_key=idempotency_key,
                    **payload.model_dump(include=set(DETAIL_FIELDS)),
                )
            )
        except IntegrityError:
            # the same key was committed for another order between the check and the
            # insert (a different order's lock); the unique constraint caught it
            # the rollback expired order, so its id comes from the payload (the same id)
            replayed = await self._replay(merchant_id, idempotency_key, payload.order_id)
            if replayed is None:
                raise
            return replayed

        await self._attach_files(merchant_id, fulfillment.id, payload.file_ids or [])

        # a paid order with proof of delivery is fulfilled; an unpaid one stays pending
        if order.status == OrderStatus.PAID:
            order.status = OrderStatus.FULFILLED
            order.updated_at = datetime.now(UTC)

        await self._commit("Error occured while creating fulfillment")

        sentry_logger.info(
            "Merchant {merchant_id} logged fulfillment {fulfillment_id}",
            merchant_id=str(merchant_id),
            fulfillment_id=str(fulfillment.id),
        )

        return fulfillment_response(
            fulfillment, await self._file_repo.for_fulfillment(fulfillment.id)
        )

    async def update_fulfillment(
        self,
        curr_merchant: Merchant,
        fulfillment_id: UUID,
        payload: FulfillmentUpdate,
        uow: UnitOfWorkRepository,
    ) -> FulfillmentResponse:
        await self._uow_fulfillments(uow)

        merchant_id: UUID = curr_merchant.id
        changes: dict = payload.model_dump(exclude_unset=True)

        fulfillment: Fulfillment = await self._get_fulfillment(
            merchant_id, fulfillment_id, for_update=True
        )

        details: dict = {field: changes[field] for field in DETAIL_FIELDS if field in changes}
        for field, value in details.items():
            setattr(fulfillment, field, value)

        if "file_ids" in changes:
            new_ids: list[UUID] = changes["file_ids"]
            current: list[StoredFile] = await self._file_repo.for_fulfillment(
                fulfillment.id, for_update=True
            )
            # detached photos become unattached; the cleanup task deletes them later
            for stored_file in current:
                if stored_file.id not in new_ids:
                    stored_file.fulfillment_id = None
            await self._attach_files(
                merchant_id,
                fulfillment.id,
                new_ids,
                already_attached={stored_file.id for stored_file in current},
            )

        if changes:
            fulfillment.updated_at = datetime.now(UTC)
            await self._commit(f"Error occured while updating fulfillment {fulfillment_id}")

        sentry_logger.info(
            "Merchant {merchant_id} updated fulfillment {fulfillment_id}",
            merchant_id=str(merchant_id),
            fulfillment_id=str(fulfillment_id),
        )

        return fulfillment_response(
            fulfillment, await self._file_repo.for_fulfillment(fulfillment.id)
        )

    async def get_fulfillment(
        self, curr_merchant: Merchant, fulfillment_id: UUID, uow: UnitOfWorkRepository
    ) -> FulfillmentResponse:
        await self._uow_fulfillments(uow)

        fulfillment: Fulfillment = await self._get_fulfillment(curr_merchant.id, fulfillment_id)
        return fulfillment_response(
            fulfillment, await self._file_repo.for_fulfillment(fulfillment.id)
        )

    async def list_fulfillments(
        self, curr_merchant: Merchant, query: FulfillmentListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[FulfillmentResponse], PageMeta]:
        await self._uow_fulfillments(uow)

        fulfillments, total = await self._fulfillment_repo.list_fulfillments(
            curr_merchant.id, query
        )
        # every page's files in one query
        files = await self._file_repo.for_fulfillments([f.id for f in fulfillments])

        return [fulfillment_response(f, files[f.id]) for f in fulfillments], PageMeta.build(
            query, total
        )
