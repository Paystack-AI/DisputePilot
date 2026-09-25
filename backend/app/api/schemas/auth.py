from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.models.enums import UserType


class AuthBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class EmailAuth(AuthBase):
    email: EmailStr


class TokenData(EmailAuth):
    user_type: UserType


class Token(AuthBase):
    access_token: str
    token_type: str = "bearer"


class MerchantSignUp(AuthBase):
    business_name: str
    paystack_integration_id: str


class EmailSignUp(MerchantSignUp):
    email: EmailStr
    password: str = Field(..., min_length=8)


class GoogleSignIn(MerchantSignUp):
    pass


class EmailLogin(EmailAuth):
    password: str = Field(..., min_length=8)


class SignUpResponse(BaseModel):
    pass


class OtpResendResponse(BaseModel):
    pass


class LogoutResponse(BaseModel):
    pass
