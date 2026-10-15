from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.models.enums import FulfillmentType


class FulfillmentSummary(BaseModel):
    """Fulfillment record as embedded in order responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID | None
    type: FulfillmentType
    delivery_date: datetime
    tracking_number: str | None
    recipient_name: str | None
    created_at: datetime
