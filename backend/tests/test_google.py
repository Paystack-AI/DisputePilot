from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.integrations.starlette_client import OAuthError
from fastapi.responses import RedirectResponse
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.core.security import Security
from app.deps import get_security
from app.main import app
from tests.conftest import NEW_PASSWORD, OTP_CODE, SIGN_UP_PAYLOAD, WRONG_PASSWORD

GOOGLE_EMAIL: str = "merchant@gmail.com"
GOOGLE_USERINFO: dict = {"sub": "google-uid-1", "email": GOOGLE_EMAIL, "email_verified": True}


def _auth(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def mock_google(userinfo: dict | None = None, error: Exception | None = None) -> Security:
    """Stand in for google: the consent redirect and the code swap for the profile"""
    security = Security()
    security.oauth = MagicMock()
    security.oauth.google.authorize_redirect = AsyncMock(
        return_value=RedirectResponse("https://accounts.google.com/o/oauth2/auth", 302)
    )
    security.oauth.google.authorize_access_token = AsyncMock(
        side_effect=error, return_value={"userinfo": userinfo or GOOGLE_USERINFO}
    )

    app.dependency_overrides[get_security] = lambda: security
    return security


async def _callback(async_client: AsyncClient, query: str = "code=g&state=s") -> dict:
    """Run the google callback and return the query sent to the frontend"""
    res: Response = await async_client.get(f"/auth/google/callback?{query}")
    assert res.status_code == 302

    location = urlparse(res.headers["location"])
    assert location.path == "/auth/google"
    return {key: value[0] for key, value in parse_qs(location.query).items()}


async def _sign_up(async_client: AsyncClient, business_name: str = "Acme Store") -> dict:
    params: dict = await _callback(async_client)
    res: Response = await async_client.post(
        "/auth/google/complete",
        json={"signup_token": params["signup_token"], "business_name": business_name},
    )
    assert res.status_code == 201
    return res.json()["data"]


class TestStart:
    @pytest.mark.asyncio
    async def test_redirects_to_google(self, async_client: AsyncClient):
        security: Security = mock_google()

        res: Response = await async_client.get("/auth/google")

        assert res.status_code == 302
        assert res.headers["location"].startswith("https://accounts.google.com")
        # the signed session cookie carries the oauth state to the callback
        assert "session" in res.cookies
        _, redirect_uri = security.oauth.google.authorize_redirect.call_args.args
        assert redirect_uri.endswith("/api/v1/auth/google/callback")


class TestNewMerchant:
    @pytest.mark.asyncio
    async def test_sign_up(self, async_client: AsyncClient):
        mock_google()

        params: dict = await _callback(async_client)
        assert set(params) == {"signup_token"}

        res: Response = await async_client.post(
            "/auth/google/complete",
            json={"signup_token": params["signup_token"], "business_name": "Acme Store"},
        )
        assert res.status_code == 201

        res = await async_client.get("/auth/me", headers=_auth(res.json()["data"]["access_token"]))
        data: dict = res.json()["data"]
        assert data["email"] == GOOGLE_EMAIL
        assert data["google_email"] == GOOGLE_EMAIL
        assert data["business_name"] == "Acme Store"
        assert data["onboarding"]["next_step"] == "connect_paystack"

    @pytest.mark.asyncio
    async def test_nothing_created_before_business_name(self, async_client: AsyncClient):
        mock_google()
        await _callback(async_client)

        # the google profile waits in redis; the email is still free
        res: Response = await async_client.post(
            "/auth/register", json={**SIGN_UP_PAYLOAD, "email": GOOGLE_EMAIL}
        )
        assert res.status_code == 201

    @pytest.mark.asyncio
    async def test_signup_token_single_use(self, async_client: AsyncClient):
        mock_google()
        params: dict = await _callback(async_client)
        payload: dict = {"signup_token": params["signup_token"], "business_name": "Acme Store"}

        await async_client.post("/auth/google/complete", json=payload)
        res: Response = await async_client.post("/auth/google/complete", json=payload)

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OAUTH_CODE"

    @pytest.mark.asyncio
    async def test_password_login_not_possible(self, async_client: AsyncClient):
        mock_google()
        await _sign_up(async_client)

        res: Response = await async_client.post(
            "/auth/login", json={"email": GOOGLE_EMAIL, "password": SIGN_UP_PAYLOAD["password"]}
        )

        # same as a wrong password; how the account signs in is not revealed
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


class TestReturningMerchant:
    @pytest.mark.asyncio
    async def test_sign_in(self, async_client: AsyncClient):
        mock_google()
        await _sign_up(async_client)

        params: dict = await _callback(async_client)
        assert set(params) == {"code"}

        res: Response = await async_client.post(
            "/auth/google/exchange", json={"code": params["code"]}
        )
        assert res.status_code == 200

        res = await async_client.get("/auth/me", headers=_auth(res.json()["data"]["access_token"]))
        assert res.json()["data"]["email"] == GOOGLE_EMAIL

    @pytest.mark.asyncio
    async def test_code_single_use(self, async_client: AsyncClient):
        mock_google()
        await _sign_up(async_client)
        params: dict = await _callback(async_client)

        await async_client.post("/auth/google/exchange", json={"code": params["code"]})
        res: Response = await async_client.post(
            "/auth/google/exchange", json={"code": params["code"]}
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OAUTH_CODE"

    @pytest.mark.asyncio
    async def test_google_session_can_not_change_password(self, async_client: AsyncClient):
        mock_google()
        tokens: dict = await _sign_up(async_client)

        res: Response = await async_client.patch(
            "/auth/me",
            json={"password": NEW_PASSWORD, "current_password": WRONG_PASSWORD},
            headers=_auth(tokens["access_token"]),
        )

        assert res.status_code == 403
        assert res.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


class TestLinking:
    @pytest.mark.asyncio
    async def test_links_verified_email_account(self, async_client: AsyncClient, verify: Response):
        mock_google({**GOOGLE_USERINFO, "email": SIGN_UP_PAYLOAD["email"]})

        # existing verified account: signed straight in, no business name step
        params: dict = await _callback(async_client)
        assert set(params) == {"code"}

        res: Response = await async_client.post(
            "/auth/google/exchange", json={"code": params["code"]}
        )
        google_tokens: dict = res.json()["data"]

        res = await async_client.get("/auth/me", headers=_auth(google_tokens["access_token"]))
        assert res.json()["data"]["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert res.json()["data"]["google_email"] == SIGN_UP_PAYLOAD["email"]

        # the password still works on the same account
        res = await async_client.post(
            "/auth/login",
            json={"email": SIGN_UP_PAYLOAD["email"], "password": SIGN_UP_PAYLOAD["password"]},
        )
        assert res.status_code == 200

        # but a google session on the linked account can not change the password
        res = await async_client.patch(
            "/auth/me",
            json={"password": NEW_PASSWORD, "current_password": SIGN_UP_PAYLOAD["password"]},
            headers=_auth(google_tokens["access_token"]),
        )
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_replaces_unverified_email_account(
        self, async_client: AsyncClient, register: Response
    ):
        # someone registered this email with their own password but never verified it
        mock_google({**GOOGLE_USERINFO, "email": SIGN_UP_PAYLOAD["email"]})

        params: dict = await _callback(async_client)
        assert set(params) == {"signup_token"}

        res: Response = await async_client.post(
            "/auth/google/complete",
            json={"signup_token": params["signup_token"], "business_name": "Real Owner Ltd"},
        )
        assert res.status_code == 201

        res = await async_client.get("/auth/me", headers=_auth(res.json()["data"]["access_token"]))
        assert res.json()["data"]["business_name"] == "Real Owner Ltd"

        # the squatter's password was wiped...
        res = await async_client.post(
            "/auth/login",
            json={"email": SIGN_UP_PAYLOAD["email"], "password": SIGN_UP_PAYLOAD["password"]},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

        # ...and their pending verification code is gone
        res = await async_client.post(
            "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
        )
        assert res.status_code == 400


class TestCallbackErrors:
    @pytest.mark.asyncio
    async def test_unverified_google_email(self, async_client: AsyncClient):
        mock_google({**GOOGLE_USERINFO, "email_verified": False})

        assert await _callback(async_client) == {"error": "google_email_not_verified"}

    @pytest.mark.asyncio
    async def test_cancelled_consent(self, async_client: AsyncClient):
        mock_google()

        params: dict = await _callback(async_client, "error=access_denied&state=s")

        assert params == {"error": "access_denied"}

    @pytest.mark.asyncio
    async def test_state_mismatch(self, async_client: AsyncClient):
        mock_google(error=OAuthError(error="mismatching_state"))

        assert await _callback(async_client) == {"error": "oauth_failed"}


class TestDeactivated:
    async def _deactivate(self, async_client: AsyncClient, tokens: dict):
        headers: dict = _auth(tokens["access_token"])
        await async_client.post("/auth/me/deactivate/request", headers=headers)
        res: Response = await async_client.post(
            "/auth/me/deactivate", json={"otp_code": OTP_CODE}, headers=headers
        )
        assert res.status_code == 204

    @pytest.mark.asyncio
    async def test_sign_in_blocked(self, async_client: AsyncClient):
        mock_google()
        await self._deactivate(async_client, await _sign_up(async_client))

        assert await _callback(async_client) == {"error": "account_deactivated"}

    @pytest.mark.asyncio
    async def test_reactivate_with_google(self, async_client: AsyncClient):
        mock_google()
        await self._deactivate(async_client, await _sign_up(async_client))

        # the intent rides in the session cookie from the start to the callback
        await async_client.get("/auth/google?intent=reactivate")
        params: dict = await _callback(async_client)
        assert set(params) == {"code"}

        res: Response = await async_client.post(
            "/auth/google/exchange", json={"code": params["code"]}
        )
        assert res.status_code == 200

        # reactivated for good: a plain sign in works again
        assert set(await _callback(async_client)) == {"code"}

    @pytest.mark.asyncio
    async def test_google_only_can_not_reactivate_with_email_code(
        self, async_client: AsyncClient, test_redis_client: Redis
    ):
        mock_google()
        await self._deactivate(async_client, await _sign_up(async_client))

        # same response as any other email, but no code: google only accounts use google
        res: Response = await async_client.post(
            "/auth/reactivate/request", json={"email": GOOGLE_EMAIL}
        )
        assert res.status_code == 202
        assert await test_redis_client.keys("otp:account_reactivation:*") == []

        res = await async_client.post(
            "/auth/reactivate", json={"email": GOOGLE_EMAIL, "otp_code": OTP_CODE}
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_linked_account_reactivates_with_email_code(
        self, async_client: AsyncClient, verify: Response
    ):
        email: str = SIGN_UP_PAYLOAD["email"]
        mock_google({**GOOGLE_USERINFO, "email": email})

        # link google to the password account, then deactivate it
        params: dict = await _callback(async_client)
        res: Response = await async_client.post(
            "/auth/google/exchange", json={"code": params["code"]}
        )
        await self._deactivate(async_client, res.json()["data"])

        # it has a password, so the email path is open
        await async_client.post("/auth/reactivate/request", json={"email": email})
        res = await async_client.post(
            "/auth/reactivate", json={"email": email, "otp_code": OTP_CODE}
        )

        assert res.status_code == 200


class TestPasswordReset:
    @pytest.mark.asyncio
    async def test_google_only_account_gets_no_code(
        self, async_client: AsyncClient, test_redis_client: Redis
    ):
        mock_google()
        await _sign_up(async_client)

        res: Response = await async_client.post(
            "/auth/password-reset", json={"email": GOOGLE_EMAIL}
        )

        # same response as any other email, but no reset code is created
        assert res.status_code == 202
        assert await test_redis_client.keys("otp:password_reset:*") == []
