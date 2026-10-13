from pydantic import Field

from app.api.schemas.auth import AuthBase


class PaystackConnect(AuthBase):
    # the prefix carries the mode: sk_test_ or sk_live_
    secret_key: str = Field(..., pattern=r"^sk_(test|live)_[A-Za-z0-9]+$", max_length=255)
