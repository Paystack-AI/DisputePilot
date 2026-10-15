import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.exc import IntegrityError

from app.api.models.merchants import Merchant
from app.api.repo.merchants import MerchantRepository
from app.api.schemas.merchants import MerchantInDB
from app.core.exceptions import MerchantExistsError, ServerError


class MerchantService:
    def __init__(self, merchant_repo: MerchantRepository):
        self._merchant_repo = merchant_repo

    async def _get_merchant(self, **filters) -> Merchant | None:
        return await self._merchant_repo.get_record(**filters)

    async def create_merchant(self, merchant: MerchantInDB, commit: bool = False) -> Merchant:
        try:
            merchant: Merchant = self._merchant_repo.add(entity=merchant)

            if commit:
                await self._merchant_repo.commit()
            else:
                await self._merchant_repo.flush()
            await self._merchant_repo.refresh(merchant)

            return merchant
        except IntegrityError as exc:
            # unique email, including concurrent sign ups
            if commit:
                await self._merchant_repo.rollback()
            raise MerchantExistsError() from exc
        except Exception as exc:
            if commit:
                await self._merchant_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating merchant")
            raise ServerError() from exc

    async def update_merchant(self, merchant: Merchant, commit: bool = False) -> Merchant:
        try:
            merchant_id = merchant.id
            merchant: Merchant = self._merchant_repo.add(model=merchant)

            if commit:
                await self._merchant_repo.commit()
            else:
                await self._merchant_repo.flush()
            await self._merchant_repo.refresh(merchant)

            return merchant
        except IntegrityError as exc:
            # unique column taken by another merchant, e.g. paystack_integration_id
            if commit:
                await self._merchant_repo.rollback()
            raise MerchantExistsError() from exc
        except Exception as exc:
            if commit:
                await self._merchant_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while updating merchant {merchant_id}", merchant_id=merchant_id
            )
            raise ServerError() from exc
