"""Read-only admin/demo views of every merchant in the installation."""

from uuid import UUID

from app.api.models.merchants import Merchant
from app.api.repo.admin import AdminRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.admin import (
    AdminDispute,
    AdminMerchantDetail,
    AdminMerchantListItem,
    AdminMerchantListQuery,
    AdminMerchantStats,
    AdminOnboarding,
    AdminOverview,
    AdminPaystack,
    AdminSettings,
    AdminTransaction,
    AdminTrust,
    AdminTrustSnapshot,
)
from app.api.schemas.pagination import PageMeta
from app.core.exceptions import NotFoundError


def _list_item(
    merchant: Merchant,
    onboarding,
    trust,
    transaction_count: int,
    dispute_count: int,
) -> AdminMerchantListItem:
    return AdminMerchantListItem(
        id=merchant.id,
        business_name=merchant.business_name,
        email=merchant.email or merchant.google_email,
        is_verified=merchant.is_verified,
        is_active=merchant.is_active,
        paystack_connected=merchant.paystack_connected_at is not None,
        paystack_mode=merchant.paystack_mode,
        onboarding_step=onboarding.current_step if onboarding else None,
        onboarding_completed=bool(onboarding and onboarding.completed_at),
        trust_state=trust.current_state if trust else None,
        transaction_count=transaction_count,
        dispute_count=dispute_count,
        created_at=merchant.created_at,
    )


class AdminService:
    async def overview(self, uow: UnitOfWorkRepository) -> AdminOverview:
        return AdminOverview(**await uow.repo(AdminRepository).overview())

    async def list_merchants(
        self, query: AdminMerchantListQuery, uow: UnitOfWorkRepository
    ) -> tuple[list[AdminMerchantListItem], PageMeta]:
        rows, total = await uow.repo(AdminRepository).list_merchants(query)
        items: list[AdminMerchantListItem] = [
            _list_item(merchant, onboarding, trust, transaction_count, dispute_count)
            for merchant, onboarding, trust, transaction_count, dispute_count in rows
        ]
        return items, PageMeta.build(query, total)

    async def merchant_detail(
        self, merchant_id: UUID, uow: UnitOfWorkRepository
    ) -> AdminMerchantDetail:
        repo: AdminRepository = uow.repo(AdminRepository)
        sources = await repo.merchant_sources(merchant_id)
        if not sources:
            raise NotFoundError("Merchant")

        merchant, onboarding, settings, trust = sources
        stats = await repo.merchant_stats(merchant_id)
        transactions = await repo.recent_transactions(merchant_id)
        disputes = await repo.recent_disputes(merchant_id)
        history = await repo.trust_history(merchant_id)

        return AdminMerchantDetail(
            id=merchant.id,
            business_name=merchant.business_name,
            email=merchant.email,
            google_email=merchant.google_email,
            is_verified=merchant.is_verified,
            is_active=merchant.is_active,
            deactivated_at=merchant.deactivated_at,
            created_at=merchant.created_at,
            updated_at=merchant.updated_at,
            paystack=AdminPaystack(
                connected=merchant.paystack_connected_at is not None,
                integration_id=merchant.paystack_integration_id,
                mode=merchant.paystack_mode,
                connected_at=merchant.paystack_connected_at,
                last_transaction_sync_at=merchant.last_transaction_sync_at,
                webhook_configured=merchant.webhook_token is not None,
                webhook_last_received_at=merchant.webhook_last_received_at,
            ),
            onboarding=(
                AdminOnboarding(
                    current_step=onboarding.current_step,
                    initial_sync_status=onboarding.initial_sync_status,
                    initial_sync_total=onboarding.initial_sync_total,
                    initial_sync_processed=onboarding.initial_sync_processed,
                    first_reconciliation_skipped=onboarding.first_reconciliation_skipped,
                    completed_at=onboarding.completed_at,
                )
                if onboarding
                else None
            ),
            settings=(
                AdminSettings(
                    notification_email=settings.notification_email,
                    auto_reconciliation_tier1=settings.auto_reconciliation_tier1,
                    default_reconciliation_range=settings.default_reconciliation_range,
                    trust_public_enabled=settings.trust_public_enabled,
                    trust_widget_enabled=settings.trust_widget_enabled,
                    timezone=settings.timezone,
                    default_currency=settings.default_currency,
                )
                if settings
                else None
            ),
            trust=(
                AdminTrust(
                    state=trust.current_state,
                    internal_score=trust.internal_score,
                    reconciliation_rate=trust.reconciliation_rate,
                    fulfillment_rate=trust.fulfillment_rate,
                    dispute_rate=trust.dispute_rate,
                    dispute_win_rate=trust.dispute_win_rate,
                    avg_response_time_pct=trust.avg_response_time_pct,
                    evidence_readiness_avg=trust.evidence_readiness_avg,
                    payments_30d=trust.payments_30d,
                    days_on_platform=trust.days_on_platform,
                    explanation=trust.explanation,
                    recommendations=trust.recommendations,
                    explained_at=trust.explained_at,
                    last_computed_at=trust.last_computed_at,
                )
                if trust
                else None
            ),
            stats=AdminMerchantStats(**dict(stats._mapping)),
            recent_transactions=[
                AdminTransaction.model_validate(transaction) for transaction in transactions
            ],
            recent_disputes=[AdminDispute.model_validate(dispute) for dispute in disputes],
            trust_history=[AdminTrustSnapshot.model_validate(snapshot) for snapshot in history],
        )
