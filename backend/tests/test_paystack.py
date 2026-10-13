import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.merchants import Merchant
from app.core.security import Security
from tests.conftest import SIGN_UP_PAYLOAD

# fake keys, kept short so they don't look like real stripe / paystack secret keys to
# secret scanners (github push protection matches sk_live_ followed by 24+ characters)
TEST_SECRET_KEY: str = "sk_test_fakekey01"  # pragma: allowlist secret
LIVE_SECRET_KEY: str = "sk_live_fakekey01"  # pragma: allowlist secret


async def _connect(async_client: AsyncClient, headers: dict, secret_key: str) -> Response:
    return await async_client.post(
        "/auth/paystack/connect", json={"secret_key": secret_key}, headers=headers
    )


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _connect(async_client, auth_headers, TEST_SECRET_KEY)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["connected"] is True
        assert data["mode"] == "test"
        assert data["connected_at"] is not None
        assert data["integration_id"] is None
        assert "secret_key" not in data

    @pytest.mark.asyncio
    async def test_key_encrypted_at_rest(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: async_sessionmaker[AsyncSession],
    ):
        await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        async with session_maker() as session:
            merchant: Merchant = (
                await session.execute(
                    select(Merchant).where(Merchant.email == SIGN_UP_PAYLOAD["email"])
                )
            ).scalar_one()

        assert merchant.paystack_secret_key != TEST_SECRET_KEY
        assert await Security().decrypt_secret_key(merchant.paystack_secret_key) == (
            TEST_SECRET_KEY
        )

    @pytest.mark.asyncio
    async def test_connect_advances_onboarding(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        res: Response = await async_client.get("/auth/me", headers=auth_headers)
        assert res.json()["data"]["onboarding"]["next_step"] == "configure_notifications"
        assert res.json()["data"]["paystack"]["connected"] is True

    @pytest.mark.asyncio
    async def test_rotate_key(self, async_client: AsyncClient, auth_headers: dict):
        first: Response = await _connect(async_client, auth_headers, TEST_SECRET_KEY)
        await async_client.post("/onboarding/notifications", json={}, headers=auth_headers)

        res: Response = await _connect(async_client, auth_headers, LIVE_SECRET_KEY)

        assert res.status_code == 200
        assert res.json()["data"]["mode"] == "live"
        assert res.json()["data"]["connected_at"] >= first.json()["data"]["connected_at"]

        # rotating the key does not send onboarding back a step
        res = await async_client.get("/auth/me", headers=auth_headers)
        assert res.json()["data"]["onboarding"]["next_step"] == "initial_sync"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "secret_key",
        ["pk_test_4f2b9c0e1a7d6b3c", "sk_prod_4f2b9c0e1a7d6b3c", "sk_test_", "not a key"],
    )
    async def test_invalid_key_format(
        self, async_client: AsyncClient, auth_headers: dict, secret_key: str
    ):
        res: Response = await _connect(async_client, auth_headers, secret_key)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await _connect(async_client, {}, TEST_SECRET_KEY)

        assert res.status_code == 401


class TestStatus:
    @pytest.mark.asyncio
    async def test_not_connected(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/auth/paystack/status", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["data"] == {
            "connected": False,
            "integration_id": None,
            "mode": None,
            "connected_at": None,
        }

    @pytest.mark.asyncio
    async def test_connected(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers, LIVE_SECRET_KEY)

        res: Response = await async_client.get("/auth/paystack/status", headers=auth_headers)

        assert res.json()["data"]["connected"] is True
        assert res.json()["data"]["mode"] == "live"
