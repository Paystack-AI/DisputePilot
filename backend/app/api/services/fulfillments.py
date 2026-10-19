import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.exc import IntegrityError

from app.api.models.fulfillments import Fulfillment
from app.api.repo.fulfillments import FulfillmentRepository
from app.api.schemas.fulfillments import FulfillmentInDB
from app.core.exceptions import ServerError


class FulfillmentService:
    def __init__(self, fulfillment_repo: FulfillmentRepository):
        self._fulfillment_repo = fulfillment_repo

    async def _get_fulfillment(self, for_update: bool = False, **filters) -> Fulfillment | None:
        return await self._fulfillment_repo.get_record(for_update=for_update, **filters)

    async def create_fulfillment(
        self, fulfillment: FulfillmentInDB, commit: bool = False
    ) -> Fulfillment:
        try:
            fulfillment: Fulfillment = self._fulfillment_repo.add(entity=fulfillment)

            if commit:
                await self._fulfillment_repo.commit()
            else:
                await self._fulfillment_repo.flush()
            await self._fulfillment_repo.refresh(fulfillment)

            return fulfillment
        except IntegrityError:
            # idempotency key already used: a retried create the caller resolves
            await self._fulfillment_repo.rollback()
            raise
        except Exception as exc:
            if commit:
                await self._fulfillment_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating fulfillment")
            raise ServerError() from exc

    async def update_fulfillment(
        self, fulfillment: Fulfillment, commit: bool = False
    ) -> Fulfillment:
        try:
            fulfillment_id = fulfillment.id
            fulfillment: Fulfillment = self._fulfillment_repo.add(model=fulfillment)

            if commit:
                await self._fulfillment_repo.commit()
            else:
                await self._fulfillment_repo.flush()
            await self._fulfillment_repo.refresh(fulfillment)

            return fulfillment
        except Exception as exc:
            if commit:
                await self._fulfillment_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while updating fulfillment {fulfillment_id}",
                fulfillment_id=fulfillment_id,
            )
            raise ServerError() from exc
