from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.models.enums import Currency, OnboardingStep, PaystackMode
from app.api.schemas.auth import AuthBase, Password


class MerchantBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MerchantInDB(MerchantBase):
    email: str | None = None
    google_id: str | None = None
    google_email: str | None = None
    hashed_password: str | None = None
    business_name: str
    paystack_integration_id: str | None = None


class MerchantSettingsInDB(MerchantBase):
    merchant_id: UUID


class MerchantOnboardingInDB(MerchantBase):
    merchant_id: UUID


class MerchantUpdate(AuthBase):
    business_name: str | None = Field(None, min_length=1, max_length=255)
    password: Password | None = None
    # required when changing password
    current_password: str | None = None


class PaystackConnection(BaseModel):
    connected: bool
    integration_id: str | None
    mode: PaystackMode | None
    connected_at: datetime | None


class OnboardingStatus(BaseModel):
    completed: bool
    next_step: OnboardingStep


class MerchantResponse(BaseModel):
    id: UUID
    email: str | None
    google_email: str | None
    business_name: str
    paystack: PaystackConnection
    timezone: str
    default_currency: Currency
    onboarding: OnboardingStatus
    created_at: datetime
