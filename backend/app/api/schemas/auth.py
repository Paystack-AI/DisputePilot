from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.api.models.enums import UserType

# emails are unique per merchant, so compare them case-insensitively
LowerEmail = Annotated[EmailStr, AfterValidator(str.lower)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
OtpCode = Annotated[str, Field(pattern=r"^\d{6}$")]


class AuthBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class EmailAuth(AuthBase):
    email: LowerEmail


class TokenData(AuthBase):
    merchant_id: UUID
    user_type: UserType
    # shared by every access and refresh token of one login, kept across refreshes
    session_id: UUID


class Token(AuthBase):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token lifetime in seconds


class RefreshToken(AuthBase):
    refresh_token: str


class MerchantSignUp(AuthBase):
    business_name: str = Field(..., min_length=1, max_length=255)


class EmailSignUp(MerchantSignUp):
    email: LowerEmail
    password: Password


class GoogleSignIn(MerchantSignUp):
    pass


class EmailLogin(EmailAuth):
    password: Password


class PasswordResetRequest(EmailAuth):
    pass


class PasswordReset(EmailAuth):
    otp_code: OtpCode
    password: Password


class AccountDeactivate(AuthBase):
    # emailed code, so every account type (including google only) confirms the same way
    otp_code: OtpCode


class ReactivateRequest(EmailAuth):
    pass


class Reactivate(EmailAuth):
    otp_code: OtpCode


class GoogleSignInExchange(AuthBase):
    code: str = Field(..., min_length=1, max_length=128)


class GoogleSignUpComplete(AuthBase):
    signup_token: str = Field(..., min_length=1, max_length=128)
    business_name: str = Field(..., min_length=1, max_length=255)
