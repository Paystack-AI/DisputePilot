from datetime import datetime

from pydantic import BaseModel


class WebhookSettingsResponse(BaseModel):
    # paste into Paystack: Settings > API Keys & Webhooks > Webhook URL (for the key's mode)
    url: str
    # true when an event arrived in the last WEBHOOK_ACTIVE_HOURS (24) hours; disputes then come
    # from the webhook instead of being polled
    active: bool
    last_received_at: datetime | None
    # the events acted on; paystack sends every event, the rest are acknowledged and dropped
    events: list[str]
    setup_steps: list[str]
