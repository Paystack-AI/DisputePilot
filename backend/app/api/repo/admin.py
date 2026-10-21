"""Read-only queries for the demo admin views. Every list is capped, and no secrets are
selected."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.models.customers import Customer
from app.api.models.disputes import Dispute
from app.api.models.enums import TransactionStatus
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.base import LIKE_ESCAPE, contains_pattern
from app.api.repo.disputes import AWAITING_STATUSES
from app.api.schemas.admin import AdminMerchantListQuery

RECENT: int = 10
TRUST_HISTORY: int = 20


class AdminRepository:
    def __init__(self, async_session: AsyncSession):
        self._async_session = async_session

    @staticmethod
    def _merchant_filters(query: AdminMerchantListQuery) -> list[Any]:
        if not query.search:
            return []
        pattern: str = contains_pattern(query.search)
        return [
            or_(
                Merchant.business_name.ilike(pattern, escape=LIKE_ESCAPE),
                Merchant.email.ilike(pattern, escape=LIKE_ESCAPE),
            )
        ]

    async def overview(self) -> dict[str, Any]:
        counts = (
            await self._async_session.execute(
                select(
                    select(func.count())
                    .select_from(Merchant)
                    .scalar_subquery()
                    .label("total_merchants"),
                    select(func.count())
                    .select_from(Merchant)
                    .where(Merchant.is_active.is_(True))
                    .scalar_subquery()
                    .label("active_merchants"),
                    select(func.count())
                    .select_from(Merchant)
                    .where(Merchant.is_verified.is_(True))
                    .scalar_subquery()
                    .label("verified_merchants"),
                    select(func.count())
                    .select_from(Merchant)
                    .where(Merchant.paystack_connected_at.is_not(None))
                    .scalar_subquery()
                    .label("paystack_connected_merchants"),
                    select(func.count())
                    .select_from(MerchantOnboarding)
                    .where(MerchantOnboarding.completed_at.is_not(None))
                    .scalar_subquery()
                    .label("onboarding_completed_merchants"),
                    select(func.count())
                    .select_from(Transaction)
                    .scalar_subquery()
                    .label("total_transactions"),
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.status == TransactionStatus.SUCCESS)
                    .scalar_subquery()
                    .label("successful_transactions"),
                    select(func.count())
                    .select_from(Dispute)
                    .scalar_subquery()
                    .label("total_disputes"),
                    select(func.count())
                    .select_from(Dispute)
                    .where(Dispute.status.in_(AWAITING_STATUSES))
                    .scalar_subquery()
                    .label("open_disputes"),
                    select(func.count()).select_from(Order).scalar_subquery().label("total_orders"),
                    select(func.count())
                    .select_from(Customer)
                    .scalar_subquery()
                    .label("total_customers"),
                )
            )
        ).one()

        state_rows = (
            await self._async_session.execute(
                select(TrustProfile.current_state, func.count())
                .group_by(TrustProfile.current_state)
                .order_by(TrustProfile.current_state)
            )
        ).all()

        result: dict[str, Any] = dict(counts._mapping)
        result["trust_states"] = {state.value: total for state, total in state_rows}
        return result

    async def list_merchants(self, query: AdminMerchantListQuery) -> tuple[list[Any], int]:
        filters: list[Any] = self._merchant_filters(query)

        transaction_count = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.merchant_id == Merchant.id)
            .scalar_subquery()
            .label("transaction_count")
        )
        dispute_count = (
            select(func.count())
            .select_from(Dispute)
            .where(Dispute.merchant_id == Merchant.id)
            .scalar_subquery()
            .label("dispute_count")
        )

        stmt = (
            select(Merchant, MerchantOnboarding, TrustProfile, transaction_count, dispute_count)
            .outerjoin(MerchantOnboarding, MerchantOnboarding.merchant_id == Merchant.id)
            .outerjoin(TrustProfile, TrustProfile.merchant_id == Merchant.id)
            # only what a list row shows: never the key, the password hash or the signals
            .options(
                load_only(
                    Merchant.id,
                    Merchant.business_name,
                    Merchant.email,
                    Merchant.google_email,
                    Merchant.is_verified,
                    Merchant.is_active,
                    Merchant.paystack_connected_at,
                    Merchant.paystack_mode,
                    Merchant.created_at,
                ),
                load_only(
                    MerchantOnboarding.id,
                    MerchantOnboarding.current_step,
                    MerchantOnboarding.completed_at,
                ),
                load_only(TrustProfile.id, TrustProfile.current_state),
            )
            .where(*filters)
            .order_by(Merchant.created_at.desc(), Merchant.id.desc())
        )

        rows = (
            await self._async_session.execute(stmt.offset(query.offset).limit(query.limit))
        ).all()
        total: int = await self._async_session.scalar(
            select(func.count()).select_from(Merchant).where(*filters)
        )
        return rows, total or 0

    async def merchant(self, merchant_id: UUID) -> Merchant | None:
        """The merchant an admin is viewing, for the merchant services to read as"""
        return await self._async_session.get(Merchant, merchant_id)

    async def merchant_sources(self, merchant_id: UUID) -> Any | None:
        """The merchant row and its one-to-one onboarding, settings and trust profile"""
        return (
            await self._async_session.execute(
                select(Merchant, MerchantOnboarding, MerchantSettings, TrustProfile)
                .outerjoin(MerchantOnboarding, MerchantOnboarding.merchant_id == Merchant.id)
                .outerjoin(MerchantSettings, MerchantSettings.merchant_id == Merchant.id)
                .outerjoin(TrustProfile, TrustProfile.merchant_id == Merchant.id)
                .where(Merchant.id == merchant_id)
            )
        ).one_or_none()

    async def merchant_stats(self, merchant_id: UUID) -> Any:
        return (
            await self._async_session.execute(
                select(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.merchant_id == merchant_id)
                    .scalar_subquery()
                    .label("transaction_count"),
                    select(func.count())
                    .select_from(Transaction)
                    .where(
                        Transaction.merchant_id == merchant_id,
                        Transaction.status == TransactionStatus.SUCCESS,
                    )
                    .scalar_subquery()
                    .label("successful_transactions"),
                    select(func.count())
                    .select_from(Dispute)
                    .where(Dispute.merchant_id == merchant_id)
                    .scalar_subquery()
                    .label("dispute_count"),
                    select(func.count())
                    .select_from(Dispute)
                    .where(
                        Dispute.merchant_id == merchant_id,
                        Dispute.status.in_(AWAITING_STATUSES),
                    )
                    .scalar_subquery()
                    .label("open_disputes"),
                    select(func.count())
                    .select_from(Order)
                    .where(Order.merchant_id == merchant_id)
                    .scalar_subquery()
                    .label("order_count"),
                    select(func.count())
                    .select_from(Customer)
                    .where(Customer.merchant_id == merchant_id)
                    .scalar_subquery()
                    .label("customer_count"),
                )
            )
        ).one()

    async def recent_transactions(self, merchant_id: UUID) -> list[Transaction]:
        return list(
            await self._async_session.scalars(
                select(Transaction)
                .where(Transaction.merchant_id == merchant_id)
                .order_by(Transaction.paystack_created_at.desc(), Transaction.id.desc())
                .limit(RECENT)
            )
        )

    async def recent_disputes(self, merchant_id: UUID) -> list[Dispute]:
        return list(
            await self._async_session.scalars(
                select(Dispute)
                .where(Dispute.merchant_id == merchant_id)
                .order_by(Dispute.created_at.desc(), Dispute.id.desc())
                .limit(RECENT)
            )
        )

    async def trust_history(self, merchant_id: UUID) -> list[TrustSnapshot]:
        return list(
            await self._async_session.scalars(
                select(TrustSnapshot)
                .where(TrustSnapshot.merchant_id == merchant_id)
                .order_by(TrustSnapshot.created_at.desc(), TrustSnapshot.id.desc())
                .limit(TRUST_HISTORY)
            )
        )
