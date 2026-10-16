import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from kombu.exceptions import OperationalError
from redis.asyncio import Redis

from app.api.models.enums import UserType
from app.api.repo.redis import RedisRepository
from app.api.schemas.auth import TokenData
from app.api.services.email import AUTH_EMAIL_PRIORITY
from app.api.services.otp import OtpService
from app.core.exceptions import ServerError
from app.core.security import Security
from tests.conftest import NEW_PASSWORD, OTP_CODE, SIGN_UP_PAYLOAD, WRONG_PASSWORD

LOGIN_PAYLOAD: dict = {
    "email": SIGN_UP_PAYLOAD["email"],
    "password": SIGN_UP_PAYLOAD["password"],
}


def _auth(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


class TestRegister:
    @pytest.mark.asyncio
    async def test_register(self, register: Response):
        assert register.status_code == 201
        assert register.json()["data"] == {
            "email": SIGN_UP_PAYLOAD["email"],
            "expires_in": 15 * 60,
        }

    @pytest.mark.asyncio
    async def test_register_queues_verification_email(
        self, register: Response, queued_emails: MagicMock
    ):
        queued_emails.assert_called_once()
        kwargs: dict = queued_emails.call_args.kwargs["kwargs"]

        assert kwargs["recipient_email"] == SIGN_UP_PAYLOAD["email"]
        assert kwargs["subject"] == "DisputePilot: Verify your email"
        assert OTP_CODE in kwargs["html"]
        assert queued_emails.call_args.kwargs["priority"] == AUTH_EMAIL_PRIORITY

    @pytest.mark.asyncio
    async def test_register_broker_unavailable(
        self, async_client: AsyncClient, queued_emails: MagicMock
    ):
        queued_emails.side_effect = OperationalError("broker unavailable")

        res: Response = await async_client.post("/auth/register", json=SIGN_UP_PAYLOAD)

        assert res.status_code == 500
        assert res.json()["error"]["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_register_creates_settings_and_onboarding(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.get("/auth/me", headers=auth_headers)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["timezone"] == "UTC"
        assert data["default_currency"] == "NGN"
        assert data["onboarding"] == {"completed": False, "next_step": "connect_paystack"}

    @pytest.mark.asyncio
    async def test_register_rolls_back_on_failure(self, async_client: AsyncClient):
        path: str = "app.api.services.auth.MerchantOnboardingService.create_onboarding"

        with patch(path, AsyncMock(side_effect=ServerError())):
            res: Response = await async_client.post("/auth/register", json=SIGN_UP_PAYLOAD)

        assert res.status_code == 500
        assert res.json()["error"]["code"] == "INTERNAL_ERROR"

        # the merchant and settings rows were rolled back, so the email is still free
        res = await async_client.post("/auth/register", json=SIGN_UP_PAYLOAD)
        assert res.status_code == 201

    @pytest.mark.asyncio
    async def test_unverified_re_sign_up_updates_details(
        self, async_client: AsyncClient, register: Response
    ):
        payload: dict = {
            **SIGN_UP_PAYLOAD,
            "password": NEW_PASSWORD,
            "business_name": "Acme Stores Ltd",
        }
        res: Response = await async_client.post("/auth/register", json=payload)
        assert res.status_code == 201

        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
        )
        assert res.status_code == 204

        res = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        assert res.status_code == 400

        res = await async_client.post(
            "/auth/login", json={**LOGIN_PAYLOAD, "password": NEW_PASSWORD}
        )
        access_token: str = res.json()["data"]["access_token"]

        res = await async_client.get("/auth/me", headers=_auth(access_token))
        assert res.json()["data"]["business_name"] == "Acme Stores Ltd"

    @pytest.mark.asyncio
    async def test_email_exists(self, async_client: AsyncClient, verify: Response):
        payload: dict = {**SIGN_UP_PAYLOAD, "email": SIGN_UP_PAYLOAD["email"].upper()}
        res: Response = await async_client.post("/auth/register", json=payload)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "MERCHANT_EXISTS"

    @pytest.mark.asyncio
    async def test_merchants_without_integration_id(
        self, async_client: AsyncClient, register: Response
    ):
        # the unique integration id is null until connected, which does not clash
        payload: dict = {**SIGN_UP_PAYLOAD, "email": "other@example.com"}
        res: Response = await async_client.post("/auth/register", json=payload)

        assert res.status_code == 201

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "override",
        [
            {"email": "invalid_email"},
            {"password": "short"},  # pragma: allowlist secret
            {"business_name": ""},
            {"unknown_field": "value"},
            # comes from paystack after connecting, not from the merchant
            {"paystack_integration_id": "1234567"},
        ],
    )
    async def test_invalid_payload(self, async_client: AsyncClient, override: dict):
        res: Response = await async_client.post(
            "/auth/register", json={**SIGN_UP_PAYLOAD, **override}
        )

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"


class TestLogin:
    @pytest.mark.asyncio
    async def test_login(self, login: Response):
        data: dict = login.json()["data"]

        assert login.status_code == 200
        assert data["access_token"]
        assert data["refresh_token"]

    @pytest.mark.asyncio
    async def test_login_email_case_insensitive(self, async_client: AsyncClient, verify: Response):
        payload: dict = {**LOGIN_PAYLOAD, "email": LOGIN_PAYLOAD["email"].upper()}
        res: Response = await async_client.post("/auth/login", json=payload)

        assert res.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "override",
        [
            {"password": WRONG_PASSWORD},
            {"email": "unknown@example.com"},
        ],
    )
    async def test_invalid_credentials(
        self, async_client: AsyncClient, verify: Response, override: dict
    ):
        res: Response = await async_client.post("/auth/login", json={**LOGIN_PAYLOAD, **override})

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_unverified(self, async_client: AsyncClient, register: Response):
        res: Response = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)

        assert res.status_code == 403
        assert res.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    @pytest.mark.asyncio
    async def test_unverified_wrong_password(self, async_client: AsyncClient, register: Response):
        # account status is only revealed after the password is accepted
        res: Response = await async_client.post(
            "/auth/login", json={**LOGIN_PAYLOAD, "password": WRONG_PASSWORD}
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


class TestVerify:
    @pytest.mark.asyncio
    async def test_verify(self, verify: Response):
        assert verify.status_code == 204

    @pytest.mark.asyncio
    async def test_wrong_code(self, async_client: AsyncClient, register: Response):
        res: Response = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": "000000"}
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_code_is_single_use(self, async_client: AsyncClient, verify: Response):
        res: Response = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_attempts_exceeded(self, async_client: AsyncClient, register: Response):
        wrong_payload: dict = {"email": SIGN_UP_PAYLOAD["email"], "otp_code": "000000"}

        for _ in range(4):
            res: Response = await async_client.post("/auth/verify", json=wrong_payload)
            assert res.json()["error"]["code"] == "INVALID_OTP"

        res = await async_client.post("/auth/verify", json=wrong_payload)
        assert res.json()["error"]["code"] == "OTP_ATTEMPTS_EXCEEDED"

        # the code is burned, even the right one no longer works...
        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
        )
        assert res.json()["error"]["code"] == "INVALID_OTP"

        # ...until a new one is requested
        res = await async_client.post(
            "/auth/verify/resend", json={"email": SIGN_UP_PAYLOAD["email"]}
        )
        assert res.status_code == 202

        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
        )
        assert res.status_code == 204

    @pytest.mark.asyncio
    async def test_resend_replaces_code(
        self, async_client: AsyncClient, register: Response, otp_code: str
    ):
        with patch.object(OtpService, "_generate_code", return_value="654321"):
            res: Response = await async_client.post(
                "/auth/verify/resend", json={"email": SIGN_UP_PAYLOAD["email"]}
            )
        assert res.status_code == 202

        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": otp_code}
        )
        assert res.json()["error"]["code"] == "INVALID_OTP"

        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": "654321"}
        )
        assert res.status_code == 204

    @pytest.mark.asyncio
    async def test_resend_unknown_email(self, async_client: AsyncClient):
        res: Response = await async_client.post(
            "/auth/verify/resend", json={"email": "unknown@example.com"}
        )

        # indistinguishable from a registered email
        assert res.status_code == 202
        assert res.json()["data"] == {"email": "unknown@example.com", "expires_in": 15 * 60}

    @pytest.mark.asyncio
    async def test_code_not_stored_in_plain_text(
        self, register: Response, test_redis_client: Redis
    ):
        keys: list[str] = await test_redis_client.keys("otp:email_verification:*")
        stored: dict = await test_redis_client.hgetall(keys[0])

        assert stored["code"] != OTP_CODE
        assert stored["attempts"] == "0"


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_rotates_token(self, async_client: AsyncClient, login: Response):
        refresh_token: str = login.json()["data"]["refresh_token"]

        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": refresh_token}
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["refresh_token"] != refresh_token

        res = await async_client.get("/auth/me", headers=_auth(data["access_token"]))
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_reused_token_revokes_all_sessions(
        self, async_client: AsyncClient, login: Response
    ):
        refresh_token: str = login.json()["data"]["refresh_token"]

        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": refresh_token}
        )
        new_tokens: dict = res.json()["data"]

        # replaying the rotated token is rejected...
        res = await async_client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_INVALID"

        # ...and ends the session the legitimate rotation is using too
        res = await async_client.post(
            "/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
        )
        assert res.status_code == 401

        res = await async_client.get("/auth/me", headers=_auth(new_tokens["access_token"]))
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_concurrent_rotation_only_one_succeeds(self, test_redis_client: Redis):
        redis_repo = RedisRepository(async_redis=test_redis_client)
        await redis_repo.create_hset(
            "sessions:test", {"sid": "jti_1", "other_sid": "other_jti"}, 60
        )

        results: list[int] = await asyncio.gather(
            *(
                redis_repo.rotate_hash_field("sessions:test", "sid", "jti_1", f"jti_{i}", 60)
                for i in range(2, 7)
            )
        )

        # one caller swaps the token, the next sees a mismatch and ends the session,
        # and the rest find the session already gone
        assert sorted(results) == [-1, 0, 0, 0, 1]
        assert await test_redis_client.hgetall("sessions:test") == {"other_sid": "other_jti"}

    @pytest.mark.asyncio
    async def test_reused_token_keeps_other_sessions(
        self, async_client: AsyncClient, login: Response
    ):
        # e.g. a laptop's session hit by a replayed refresh token...
        laptop_tokens: dict = login.json()["data"]
        refresh_payload: dict = {"refresh_token": laptop_tokens["refresh_token"]}

        # ...while the same merchant is signed in on mobile
        res: Response = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        mobile_tokens: dict = res.json()["data"]

        await async_client.post("/auth/refresh", json=refresh_payload)
        res = await async_client.post("/auth/refresh", json=refresh_payload)
        assert res.status_code == 401

        res = await async_client.get("/auth/me", headers=_auth(mobile_tokens["access_token"]))
        assert res.status_code == 200

        res = await async_client.post(
            "/auth/refresh", json={"refresh_token": mobile_tokens["refresh_token"]}
        )
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_access_token_rejected(self, async_client: AsyncClient, login: Response):
        access_token: str = login.json()["data"]["access_token"]
        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": access_token}
        )

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_expired_token(self, async_client: AsyncClient, register: Response):
        token_data = TokenData(merchant_id=uuid4(), user_type=UserType.EMAIL, session_id=uuid4())
        refresh_token, _ = await Security().create_refresh_token(token_data, expire_time=-1)

        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


class TestMe:
    @pytest.mark.asyncio
    async def test_get_me(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/auth/me", headers=auth_headers)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["email"] == SIGN_UP_PAYLOAD["email"]
        assert data["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert data["paystack"] == {
            "connected": False,
            "integration_id": None,
            "mode": None,
            "connected_at": None,
        }
        assert "hashed_password" not in data

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await async_client.get("/auth/me")

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_expired_access_token(self, async_client: AsyncClient, register: Response):
        token_data = TokenData(merchant_id=uuid4(), user_type=UserType.EMAIL, session_id=uuid4())
        access_token: str = await Security().create_access_token(token_data, expire_time=-1)

        res: Response = await async_client.get("/auth/me", headers=_auth(access_token))

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_EXPIRED"

    @pytest.mark.asyncio
    async def test_update_business_name(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.patch(
            "/auth/me", json={"business_name": "Acme Stores Ltd"}, headers=auth_headers
        )

        assert res.status_code == 200
        assert res.json()["data"]["business_name"] == "Acme Stores Ltd"

    @pytest.mark.asyncio
    async def test_email_can_not_be_updated(self, async_client: AsyncClient, auth_headers: dict):
        payload: dict = {
            "email": "new@example.com",
            "current_password": SIGN_UP_PAYLOAD["password"],
        }
        res: Response = await async_client.patch("/auth/me", json=payload, headers=auth_headers)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("current_password", [None, WRONG_PASSWORD])
    async def test_update_password_requires_current_password(
        self, async_client: AsyncClient, auth_headers: dict, current_password: str | None
    ):
        payload: dict = {"password": NEW_PASSWORD}
        if current_password:
            payload["current_password"] = current_password

        res: Response = await async_client.patch("/auth/me", json=payload, headers=auth_headers)

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_update_password_revokes_sessions(
        self, async_client: AsyncClient, login: Response
    ):
        tokens: dict = login.json()["data"]

        # a second session that must be signed out as well
        res: Response = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        other_tokens: dict = res.json()["data"]

        payload: dict = {
            "password": NEW_PASSWORD,
            "current_password": SIGN_UP_PAYLOAD["password"],
        }
        res = await async_client.patch(
            "/auth/me", json=payload, headers=_auth(tokens["access_token"])
        )
        assert res.status_code == 200

        for session in (tokens, other_tokens):
            res = await async_client.get("/auth/me", headers=_auth(session["access_token"]))
            assert res.status_code == 401
            assert res.json()["error"]["code"] == "TOKEN_INVALID"

            res = await async_client.post(
                "/auth/refresh", json={"refresh_token": session["refresh_token"]}
            )
            assert res.status_code == 401

        res = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        assert res.status_code == 400

        res = await async_client.post(
            "/auth/login", json={**LOGIN_PAYLOAD, "password": NEW_PASSWORD}
        )
        assert res.status_code == 200


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout(self, async_client: AsyncClient, login: Response):
        tokens: dict = login.json()["data"]

        res: Response = await async_client.post(
            "/auth/logout", headers=_auth(tokens["access_token"])
        )
        assert res.status_code == 204

        res = await async_client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert res.status_code == 401

        # the access token is still within its lifetime but its session has ended
        res = await async_client.get("/auth/me", headers=_auth(tokens["access_token"]))
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_logout_after_refresh(self, async_client: AsyncClient, login: Response):
        tokens: dict = login.json()["data"]

        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        new_tokens: dict = res.json()["data"]

        res = await async_client.post("/auth/logout", headers=_auth(new_tokens["access_token"]))
        assert res.status_code == 204

        # the access token from before the refresh shares the session, so it ends too
        res = await async_client.get("/auth/me", headers=_auth(tokens["access_token"]))
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_keeps_other_sessions(self, async_client: AsyncClient, login: Response):
        tokens: dict = login.json()["data"]

        res: Response = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        other_tokens: dict = res.json()["data"]

        res = await async_client.post("/auth/logout", headers=_auth(tokens["access_token"]))
        assert res.status_code == 204

        res = await async_client.get("/auth/me", headers=_auth(other_tokens["access_token"]))
        assert res.status_code == 200

        res = await async_client.post(
            "/auth/refresh", json={"refresh_token": other_tokens["refresh_token"]}
        )
        assert res.status_code == 200


class TestPasswordReset:
    RESET_PAYLOAD: dict = {
        "email": SIGN_UP_PAYLOAD["email"],
        "otp_code": OTP_CODE,
        "password": NEW_PASSWORD,
    }

    @pytest.mark.asyncio
    async def test_reset_password(self, async_client: AsyncClient, login: Response):
        tokens: dict = login.json()["data"]

        res: Response = await async_client.post(
            "/auth/password-reset", json={"email": SIGN_UP_PAYLOAD["email"]}
        )
        assert res.status_code == 202

        res = await async_client.post("/auth/password-reset/confirm", json=self.RESET_PAYLOAD)
        assert res.status_code == 204

        # sessions opened with the old password are signed out
        res = await async_client.get("/auth/me", headers=_auth(tokens["access_token"]))
        assert res.status_code == 401

        res = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        assert res.status_code == 400

        res = await async_client.post(
            "/auth/login", json={**LOGIN_PAYLOAD, "password": NEW_PASSWORD}
        )
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_without_requesting_code(self, async_client: AsyncClient, verify: Response):
        res: Response = await async_client.post(
            "/auth/password-reset/confirm", json=self.RESET_PAYLOAD
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_verification_code_rejected(self, async_client: AsyncClient, register: Response):
        # the email verification code can not be used to reset the password
        res: Response = await async_client.post(
            "/auth/password-reset/confirm", json=self.RESET_PAYLOAD
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_unknown_email(self, async_client: AsyncClient, queued_emails: MagicMock):
        res: Response = await async_client.post(
            "/auth/password-reset", json={"email": "unknown@example.com"}
        )

        assert res.status_code == 202
        assert res.json()["data"] == {"email": "unknown@example.com", "expires_in": 15 * 60}
        queued_emails.assert_not_called()


class TestDeactivation:
    @pytest.mark.asyncio
    async def test_deactivate_and_reactivate(self, async_client: AsyncClient, login: Response):
        tokens: dict = login.json()["data"]

        res: Response = await async_client.post(
            "/auth/me/deactivate/request", headers=_auth(tokens["access_token"])
        )
        assert res.status_code == 202

        res = await async_client.post(
            "/auth/me/deactivate",
            json={"otp_code": OTP_CODE},
            headers=_auth(tokens["access_token"]),
        )
        assert res.status_code == 204

        res = await async_client.get("/auth/me", headers=_auth(tokens["access_token"]))
        assert res.status_code == 401

        res = await async_client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert res.status_code == 401

        res = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "ACCOUNT_DEACTIVATED"

        # soft deleted: the email is still taken
        res = await async_client.post("/auth/register", json=SIGN_UP_PAYLOAD)
        assert res.status_code == 409

        email: dict = {"email": SIGN_UP_PAYLOAD["email"]}

        res = await async_client.post("/auth/reactivate/request", json=email)
        assert res.status_code == 202

        res = await async_client.post("/auth/reactivate", json={**email, "otp_code": OTP_CODE})
        assert res.status_code == 200

        res = await async_client.get("/auth/me", headers=_auth(res.json()["data"]["access_token"]))
        assert res.status_code == 200

        res = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_deactivate_wrong_code(self, async_client: AsyncClient, auth_headers: dict):
        await async_client.post("/auth/me/deactivate/request", headers=auth_headers)

        res: Response = await async_client.post(
            "/auth/me/deactivate", json={"otp_code": "000000"}, headers=auth_headers
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

        res = await async_client.get("/auth/me", headers=auth_headers)
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_deactivate_without_requesting_code(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.post(
            "/auth/me/deactivate", json={"otp_code": OTP_CODE}, headers=auth_headers
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_reactivate_active_account(self, async_client: AsyncClient, verify: Response):
        email: dict = {"email": SIGN_UP_PAYLOAD["email"]}

        # nothing to reactivate: the request responds the same but sends no code
        res: Response = await async_client.post("/auth/reactivate/request", json=email)
        assert res.status_code == 202

        res = await async_client.post("/auth/reactivate", json={**email, "otp_code": OTP_CODE})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_reactivate_unknown_email(self, async_client: AsyncClient):
        res: Response = await async_client.post(
            "/auth/reactivate/request", json={"email": "unknown@example.com"}
        )

        assert res.status_code == 202
        assert res.json()["data"] == {"email": "unknown@example.com", "expires_in": 15 * 60}

    @pytest.mark.asyncio
    async def test_reactivated_session_can_not_change_password(
        self, async_client: AsyncClient, login: Response
    ):
        headers: dict = _auth(login.json()["data"]["access_token"])
        email: dict = {"email": SIGN_UP_PAYLOAD["email"]}

        await async_client.post("/auth/me/deactivate/request", headers=headers)
        await async_client.post("/auth/me/deactivate", json={"otp_code": OTP_CODE}, headers=headers)
        await async_client.post("/auth/reactivate/request", json=email)
        res: Response = await async_client.post(
            "/auth/reactivate", json={**email, "otp_code": OTP_CODE}
        )

        # signed in through the inbox, not the password
        res = await async_client.patch(
            "/auth/me",
            json={"password": NEW_PASSWORD, "current_password": SIGN_UP_PAYLOAD["password"]},
            headers=_auth(res.json()["data"]["access_token"]),
        )

        assert res.status_code == 403
        assert res.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


class TestRateLimit:
    @pytest.mark.asyncio
    @pytest.mark.rate_limited
    async def test_rate_limited(self, async_client: AsyncClient):
        for _ in range(10):
            await async_client.post("/auth/login", json=LOGIN_PAYLOAD)

        res: Response = await async_client.post("/auth/login", json=LOGIN_PAYLOAD)

        assert res.status_code == 429
        assert res.json()["error"]["code"] == "RATE_LIMITED"
        assert res.headers["Retry-After"] == str(15 * 60)
