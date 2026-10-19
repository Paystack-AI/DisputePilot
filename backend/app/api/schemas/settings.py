from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.models.enums import Currency
from app.api.schemas.auth import AuthBase


def _reject_null(value):
    if value is None:
        raise ValueError("can not be null")
    return value


class NotificationPreferences(AuthBase):
    # alerts go by email (and in-app);
    notification_email: bool | None = None

    _validate_notification_email = field_validator("notification_email", mode="before")(
        _reject_null
    )


class SettingsUpdate(NotificationPreferences):
    auto_reconciliation_tier1: bool | None = None
    default_reconciliation_range: int | None = Field(None, ge=1, le=90)  # days
    trust_public_enabled: bool | None = None
    trust_widget_enabled: bool | None = None
    timezone: str | None = None
    default_currency: Currency | None = None

    _validate_not_null = field_validator(
        "auto_reconciliation_tier1",
        "default_reconciliation_range",
        "trust_public_enabled",
        "trust_widget_enabled",
        "timezone",
        "default_currency",
        mode="before",
    )(_reject_null)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("must be an IANA timezone, e.g. Africa/Lagos") from exc
        return value


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_email: bool
    auto_reconciliation_tier1: bool
    default_reconciliation_range: int
    trust_public_enabled: bool
    trust_widget_enabled: bool
    timezone: str
    default_currency: Currency
    updated_at: datetime | None
