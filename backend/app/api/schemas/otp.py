from pydantic import BaseModel

from app.api.schemas.auth import AuthBase, LowerEmail, OtpCode


class OtpBase(AuthBase):
    email: LowerEmail


class EmailVerify(OtpBase):
    otp_code: OtpCode


class ResendOtp(OtpBase):
    pass


class OtpSentResponse(BaseModel):
    email: str
    expires_in: int  # seconds until the code expires
