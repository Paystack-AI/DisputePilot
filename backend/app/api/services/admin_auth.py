"""Operator authentication: a separate admins table and short-lived JWTs.

Admin tokens carry scope=admin and are accepted only by /admin. They are also tied to a
redis session hash, so multiple devices can stay signed in independently and logout
revokes only that device. Each request rechecks that the account still exists and is
active.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.admins import Admin
from app.api.repo.admins import AdminAccountRepository
from app.api.repo.redis import RedisRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.admin import AdminLogin
from app.core.config import get_settings
from app.core.exceptions import AdminAuthenticationError, CredentialError, ServerError
from app.core.security import Security

SETTINGS = get_settings()


class AdminAuthService:
    def __init__(self, redis_repo: RedisRepository):
        self._redis_repo = redis_repo

    @staticmethod
    def _sessions_key(admin_id: str) -> str:
        """One hash per admin, like a merchant's sessions: session id -> active.

        Logging in on another device adds a field, logout removes only that device's
        field, and deleting the hash ends all of the admin's sessions.
        """
        return f"admin_sessions:{admin_id}"

    async def login(
        self, payload: AdminLogin, security: Security, uow: UnitOfWorkRepository
    ) -> tuple[Admin, str]:
        repo: AdminAccountRepository = uow.repo(AdminAccountRepository)
        admin: Admin | None = await repo.get_by_email(payload.email)

        if not admin or not admin.is_active:
            sentry_logger.error("Admin login attempted for an unknown or inactive account")
            raise CredentialError()
        if not await security.verify_password(payload.password, admin.hashed_password):
            sentry_logger.error(
                "Admin login with a wrong password for admin {admin_id}", admin_id=str(admin.id)
            )
            raise CredentialError()

        session_id: UUID = uuid4()
        token: str = await security.create_admin_access_token(admin.id, session_id)

        try:
            await self._redis_repo.create_hset(
                self._sessions_key(str(admin.id)),
                {str(session_id): "1"},
                SETTINGS.ACCESS_TOKEN_EXPIRE_TIME * 60,
            )
            admin.last_login_at = datetime.now(UTC)
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            try:
                await self._redis_repo.delete_hash_field(
                    self._sessions_key(str(admin.id)), str(session_id)
                )
            except Exception:
                pass
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occurred while creating admin session")
            raise ServerError() from exc

        return admin, token

    async def current_admin(self, claims: dict, uow: UnitOfWorkRepository) -> Admin:
        try:
            admin_id: UUID = UUID(claims["sub"])
            session_id: str = claims["sid"]
        except (KeyError, ValueError, TypeError) as exc:
            raise AdminAuthenticationError() from exc

        try:
            active: bool = await self._redis_repo.hash_field_exists(
                self._sessions_key(str(admin_id)), session_id
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occurred while checking admin session")
            raise ServerError() from exc

        if not active:
            raise AdminAuthenticationError()

        admin: Admin | None = await uow.repo(AdminAccountRepository).get_by_id(admin_id)
        if not admin or not admin.is_active:
            raise AdminAuthenticationError()
        return admin

    async def logout(self, claims: dict) -> None:
        try:
            await self._redis_repo.delete_hash_field(
                self._sessions_key(claims["sub"]), claims["sid"]
            )
        except KeyError as exc:
            raise AdminAuthenticationError() from exc
