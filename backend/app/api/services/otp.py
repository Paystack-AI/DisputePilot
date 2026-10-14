import hashlib
import hmac
import secrets
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.enums import OtpPurpose
from app.api.repo.redis import RedisRepository
from app.core.config import get_settings
from app.core.exceptions import InvalidOtpError, OtpAttemptsExceededError, ServerError


class OtpService:
    """One live 6-digit code per merchant and purpose, kept in redis.

    The key is replaced on every new code, so issuing a code invalidates the
    previous one; the ttl handles expiry and the code is deleted once used or
    once max attempts is reached. Only an hmac of the code is stored.
    """

    def __init__(self, redis_repo: RedisRepository):
        self._redis_repo = redis_repo

    SETTINGS = get_settings()

    @staticmethod
    def _otp_key(purpose: OtpPurpose, merchant_id: UUID) -> str:
        return f"otp:{purpose}:{merchant_id}"

    @staticmethod
    def _generate_code() -> str:
        return str(secrets.randbelow(900000) + 100000)

    def _hash_code(self, code: str) -> str:
        return hmac.new(
            self.SETTINGS.OTP_SECRET_KEY.encode(), code.encode(), hashlib.sha256
        ).hexdigest()

    @property
    def expires_in(self) -> int:
        """Code lifetime in seconds"""
        return self.SETTINGS.OTP_EXPIRE_TIME * 60

    async def create_otp(self, merchant_id: UUID, purpose: OtpPurpose) -> str:
        code: str = self._generate_code()

        try:
            key: str = self._otp_key(purpose, merchant_id)
            # replace rather than merge so a new code also resets the attempts
            await self._redis_repo.delete_key(key)
            await self._redis_repo.create_hset(
                key, {"code": self._hash_code(code), "attempts": 0}, self.expires_in
            )
            return code
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while creating {purpose} otp for merchant {merchant_id}",
                purpose=purpose,
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

    async def delete_otp(self, merchant_id: UUID, purpose: OtpPurpose):
        """Discard a pending code, e.g. once the account no longer needs it"""
        try:
            await self._redis_repo.delete_key(self._otp_key(purpose, merchant_id))
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while deleting {purpose} otp for merchant {merchant_id}",
                purpose=purpose,
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

    async def verify_otp(self, merchant_id: UUID, purpose: OtpPurpose, code: str):
        try:
            result: int = await self._redis_repo.consume_code(
                self._otp_key(purpose, merchant_id),
                self._hash_code(code),
                self.SETTINGS.OTP_MAX_ATTEMPTS,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Error occured while verifying {purpose} otp for merchant {merchant_id}",
                purpose=purpose,
                merchant_id=str(merchant_id),
            )
            raise ServerError() from exc

        if result == 1:
            return

        sentry_logger.error(
            "Invalid {purpose} otp received for merchant {merchant_id}",
            purpose=purpose,
            merchant_id=str(merchant_id),
        )

        if result == -1:
            raise OtpAttemptsExceededError()
        raise InvalidOtpError()
