from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.api.models.enums import OtpStatus


class OtpBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr


class EmailVerify(OtpBase):
    otp_code: str


class ResendOtp(OtpBase):
    pass


class OtpInDB(OtpBase):
    otp: str
    user_id: UUID
    status: OtpStatus = "valid"
    expires_at: datetime
