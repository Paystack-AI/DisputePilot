import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.exc import IntegrityError

from app.api.models.customers import Customer
from app.api.models.merchants import Merchant
from app.api.repo.customers import CustomerRepository
from app.api.schemas.customers import CustomerInDB
from app.core.exceptions import ServerError


def is_merchant_email(merchant: Merchant, email: str | None) -> bool:
    """Payments made with the merchant's own email (e.g. entered at checkout for walk-in
    buyers) belong to many people, so the customer is shared"""
    return email is not None and email in (merchant.email, merchant.google_email)


class CustomerService:
    def __init__(self, customer_repo: CustomerRepository):
        self._customer_repo = customer_repo

    async def _get_customer(self, for_update: bool = False, **filters) -> Customer | None:
        return await self._customer_repo.get_record(for_update=for_update, **filters)

    async def get_or_create_customer(self, customer: CustomerInDB) -> Customer:
        """For payer emails seen on orders and, later, the paystack sync"""
        try:
            return await self._customer_repo.get_or_create_by_email(customer)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while getting or creating customer")
            raise ServerError() from exc

    async def create_customer(self, customer: CustomerInDB, commit: bool = False) -> Customer:
        """IntegrityError (email or paystack code taken) is raised for the caller to map"""
        try:
            customer: Customer = self._customer_repo.add(entity=customer)

            if commit:
                await self._customer_repo.commit()
            else:
                await self._customer_repo.flush()
            await self._customer_repo.refresh(customer)

            return customer
        except IntegrityError:
            await self._customer_repo.rollback()
            raise
        except Exception as exc:
            if commit:
                await self._customer_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while creating customer")
            raise ServerError() from exc

    async def update_customer(self, customer: Customer, commit: bool = False) -> Customer:
        """IntegrityError (email taken) is raised for the caller to map"""
        try:
            customer_id = customer.id
            customer: Customer = self._customer_repo.add(model=customer)

            if commit:
                await self._customer_repo.commit()
            else:
                await self._customer_repo.flush()
            await self._customer_repo.refresh(customer)

            return customer
        except IntegrityError:
            await self._customer_repo.rollback()
            raise
        except Exception as exc:
            if commit:
                await self._customer_repo.rollback()

            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while updating customer {customer_id}", customer_id=customer_id
            )
            raise ServerError() from exc
