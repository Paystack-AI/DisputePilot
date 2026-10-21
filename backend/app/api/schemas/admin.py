"""Read-only demo admin views. They show merchants and the data we hold for them; no
secrets (password hashes, Paystack keys, webhook tokens) are ever returned."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.models.enums import (
    Currency,
    DisputeCategory,
    DisputeStatus,
    EvidenceState,
    InitialSyncStatus,
    OnboardingStep,
    PaystackMode,
    ReconciliationStatus,
    SubmissionState,
    TransactionChannel,
    TransactionStatus,
    TrustState,
)
from app.api.schemas.auth import AuthBase, LowerEmail, Password
from app.api.schemas.pagination import PageParams


class AdminLogin(AuthBase):
    email: LowerEmail
    password: Password


class AdminInDB(BaseModel):
    email: str
    name: str | None = None
    hashed_password: str
    is_active: bool = True


class AdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AdminMerchantListQuery(PageParams):
    # business name or email
    search: str | None = Field(None, max_length=100)


class AdminMerchantListItem(BaseModel):
    id: UUID
    business_name: str
    email: str | None
    is_verified: bool
    is_active: bool
    paystack_connected: bool
    paystack_mode: PaystackMode | None
    onboarding_step: OnboardingStep | None
    onboarding_completed: bool
    trust_state: TrustState | None
    transaction_count: int
    dispute_count: int
    created_at: datetime


class AdminOverview(BaseModel):
    total_merchants: int
    active_merchants: int
    verified_merchants: int
    paystack_connected_merchants: int
    onboarding_completed_merchants: int
    total_transactions: int
    successful_transactions: int
    total_disputes: int
    open_disputes: int
    total_orders: int
    total_customers: int
    trust_states: dict[str, int]


class AdminPaystack(BaseModel):
    connected: bool
    integration_id: str | None
    mode: PaystackMode | None
    connected_at: datetime | None
    last_transaction_sync_at: datetime | None
    webhook_configured: bool
    webhook_last_received_at: datetime | None


class AdminOnboarding(BaseModel):
    current_step: OnboardingStep
    initial_sync_status: InitialSyncStatus
    initial_sync_total: int | None
    initial_sync_processed: int
    first_reconciliation_skipped: bool
    completed_at: datetime | None


class AdminSettings(BaseModel):
    notification_email: bool
    auto_reconciliation_tier1: bool
    default_reconciliation_range: int
    trust_public_enabled: bool
    trust_widget_enabled: bool
    timezone: str
    default_currency: Currency


class AdminTrust(BaseModel):
    state: TrustState
    internal_score: int | None
    reconciliation_rate: float | None
    fulfillment_rate: float | None
    dispute_rate: float | None
    dispute_win_rate: float | None
    avg_response_time_pct: float | None
    evidence_readiness_avg: float | None
    payments_30d: int | None
    days_on_platform: int | None
    explanation: str | None
    recommendations: list[dict] | None
    explained_at: datetime | None
    last_computed_at: datetime | None


class AdminMerchantStats(BaseModel):
    transaction_count: int
    successful_transactions: int
    dispute_count: int
    open_disputes: int
    order_count: int
    customer_count: int


class AdminTransaction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str = Field(validation_alias="paystack_reference")
    paystack_transaction_id: str
    amount: int
    currency: Currency
    channel: TransactionChannel
    status: TransactionStatus
    reconciliation_status: ReconciliationStatus
    customer_email: str | None
    customer_name: str | None
    order_id: UUID | None
    paid_at: datetime | None
    created_at: datetime = Field(validation_alias="paystack_created_at")

    @field_validator("paystack_transaction_id", mode="before")
    @classmethod
    def stringify_paystack_id(cls, value: int | str) -> str:
        return str(value)


class AdminDispute(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str = Field(validation_alias="paystack_reference")
    paystack_dispute_id: str
    status: DisputeStatus
    category: DisputeCategory | None
    amount: int
    currency: Currency
    created_at: datetime
    due_at: datetime
    resolved_at: datetime | None
    evidence_state: EvidenceState | None
    submission_state: SubmissionState | None

    @field_validator("paystack_dispute_id", mode="before")
    @classmethod
    def stringify_paystack_id(cls, value: int | str) -> str:
        return str(value)


class AdminTrustSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    state: TrustState
    internal_score: int | None
    reason: str
    summary: str | None
    signals: dict
    created_at: datetime


class AdminMerchantDetail(BaseModel):
    id: UUID
    business_name: str
    email: str | None
    google_email: str | None
    is_verified: bool
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    paystack: AdminPaystack
    onboarding: AdminOnboarding | None
    settings: AdminSettings | None
    trust: AdminTrust | None
    stats: AdminMerchantStats
    recent_transactions: list[AdminTransaction]
    recent_disputes: list[AdminDispute]
    trust_history: list[AdminTrustSnapshot]
