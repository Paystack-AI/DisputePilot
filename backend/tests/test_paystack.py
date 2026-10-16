import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.merchants import Merchant
from app.core.security import Security
from tests.conftest import SIGN_UP_PAYLOAD, FakePaystack

# fake keys, kept short so they don't look like real stripe / paystack secret keys to
# secret scanners (github push protection matches sk_live_ followed by 24+ characters)
TEST_SECRET_KEY: str = "sk_test_fakekey01"  # pragma: allowlist secret
LIVE_SECRET_KEY: str = "sk_live_fakekey01"  # pragma: allowlist secret


def _transactions(integration: int) -> dict:
    return {"status": True, "message": "ok", "data": [{"id": 1, "integration": integration}]}


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

    @pytest.mark.asyncio
    async def test_key_checked_with_paystack(
        self, async_client: AsyncClient, auth_headers: dict, paystack_api: FakePaystack
    ):
        await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        (request,) = paystack_api.requests
        assert request.method == "GET"
        assert request.url.path == "/transaction"
        assert request.url.params["perPage"] == "1"
        assert request.headers["Authorization"] == f"Bearer {TEST_SECRET_KEY}"

    @pytest.mark.asyncio
    async def test_key_rejected_by_paystack(
        self, async_client: AsyncClient, auth_headers: dict, paystack_api: FakePaystack
    ):
        paystack_api.respond(
            "GET", "/transaction", 401, {"status": False, "message": "Invalid key"}
        )

        res: Response = await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "PAYSTACK_KEY_INVALID"

        # nothing is stored for a rejected key
        res = await async_client.get("/auth/paystack/status", headers=auth_headers)
        assert res.json()["data"]["connected"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    async def test_paystack_unavailable(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        paystack_api: FakePaystack,
        status_code: int,
    ):
        paystack_api.respond("GET", "/transaction", status_code, {"status": False})

        res: Response = await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        assert res.status_code == 502
        assert res.json()["error"]["code"] == "PAYSTACK_UPSTREAM_ERROR"

    @pytest.mark.asyncio
    async def test_integration_id_read_from_transactions(
        self, async_client: AsyncClient, auth_headers: dict, paystack_api: FakePaystack
    ):
        paystack_api.respond("GET", "/transaction", json=_transactions(integration=100982))

        res: Response = await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        assert res.json()["data"]["integration_id"] == "100982"

    @pytest.mark.asyncio
    async def test_rotate_to_another_integration(
        self, async_client: AsyncClient, auth_headers: dict, paystack_api: FakePaystack
    ):
        paystack_api.respond("GET", "/transaction", json=_transactions(integration=100982))
        await _connect(async_client, auth_headers, TEST_SECRET_KEY)

        paystack_api.respond("GET", "/transaction", json=_transactions(integration=555))
        res: Response = await _connect(async_client, auth_headers, LIVE_SECRET_KEY)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "PAYSTACK_INTEGRATION_MISMATCH"

        # the connected key is kept
        res = await async_client.get("/auth/paystack/status", headers=auth_headers)
        assert res.json()["data"]["mode"] == "test"
        assert res.json()["data"]["integration_id"] == "100982"


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
