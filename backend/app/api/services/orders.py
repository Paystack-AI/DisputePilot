import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.exc import IntegrityError

from app.api.models.orders import Order
from app.api.repo.orders import OrderRepository
from app.api.schemas.orders import OrderInDB
from app.core.exceptions import OrderNumberExistsError, ServerError


class OrderService:
    def __init__(self, order_repo: OrderRepository):
        self._order_repo = order_repo

    async def _get_order(self, for_update: bool = False, **filters) -> Order | None:
        return await self._order_repo.get_record(for_update=for_update, **filters)

    async def create_order(self, order: OrderInDB, commit: bool = False) -> Order:
        try:
            order: Order = self._order_repo.add(entity=order)

            if commit:
                await self._order_repo.commit()
            else:
                await self._order_repo.flush()
            await self._order_repo.refresh(order)

            return order
        except IntegrityError as exc:
            # order number taken for this merchant (ignoring case), including concurrent creates
            await self._order_repo.rollback()
            raise OrderNumberExistsError() from exc
        except Exception as exc:
            if commit:
                await self._order_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating order")
            raise ServerError() from exc

    async def update_order(self, order: Order, commit: bool = False) -> Order:
        try:
            order_id = order.id
            order: Order = self._order_repo.add(model=order)

            if commit:
                await self._order_repo.commit()
            else:
                await self._order_repo.flush()
            await self._order_repo.refresh(order)

            return order
        except IntegrityError as exc:
            await self._order_repo.rollback()
            raise OrderNumberExistsError() from exc
        except Exception as exc:
            if commit:
                await self._order_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while updating order {order_id}", order_id=order_id)
            raise ServerError() from exc
