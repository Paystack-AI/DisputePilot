from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.admins import Admin
from app.api.models.enums import (
    DisputeStatus,
    ReconciliationStatus,
    TransactionStatus,
    TrustState,
)
from app.api.models.trust_profiles import TrustProfile
from app.core.security import Security
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_dispute, add_transaction, merchant_id

SessionMaker = async_sessionmaker[AsyncSession]

ADMIN_EMAIL = "operator@example.com"
ADMIN_PASSWORD = "admin_password"  # pragma: allowlist secret
LOGIN = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}


async def _merchant(session_maker: SessionMaker) -> UUID:
    return await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])


async def _create_admin(
    session_maker: SessionMaker,
    email: str = ADMIN_EMAIL,
    password: str = ADMIN_PASSWORD,
    is_active: bool = True,
) -> UUID:
    security = Security()
    async with session_maker() as session:
        admin = Admin(
            email=email,
            name="Operator",
            hashed_password=await security.hash_password(password),
            is_active=is_active,
        )
        session.add(admin)
        await session.commit()
        return admin.id


async def _login(async_client: AsyncClient, email: str = ADMIN_EMAIL) -> Response:
    return await async_client.post(
        "/admin/auth/login", json={"email": email, "password": ADMIN_PASSWORD}
    )


@pytest_asyncio.fixture
async def admin_headers(async_client: AsyncClient, session_maker: SessionMaker) -> dict:
    await _create_admin(session_maker)
    res: Response = await _login(async_client)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


class TestAdminAccess:
    @pytest.mark.asyncio
    async def test_login_returns_an_admin_token(
        self, async_client: AsyncClient, session_maker: SessionMaker
    ):
        await _create_admin(session_maker)

        res: Response = await _login(async_client)
        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        assert data["token_type"] == "bearer"
        assert data["access_token"]
        assert data["expires_in"] > 0

        headers = {"Authorization": f"Bearer {data['access_token']}"}
        me = await async_client.get("/admin/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["data"]["email"] == ADMIN_EMAIL

        # admin tokens are not accepted by merchant endpoints either
        merchant = await async_client.get("/auth/me", headers=headers)
        assert merchant.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_password_is_rejected(
        self, async_client: AsyncClient, session_maker: SessionMaker
    ):
        await _create_admin(session_maker)
        res: Response = await async_client.post(
            "/admin/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrong_password"},  # pragma: allowlist secret
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_inactive_admin_can_not_log_in(
        self, async_client: AsyncClient, session_maker: SessionMaker
    ):
        await _create_admin(session_maker, is_active=False)
        res: Response = await _login(async_client)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_missing_token_is_rejected(self, async_client: AsyncClient):
        res: Response = await async_client.get("/admin/overview")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "ADMIN_TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_merchant_token_is_not_an_admin_token(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        res: Response = await async_client.get("/admin/overview", headers=auth_headers)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "ADMIN_TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_logout_revokes_the_token(self, async_client: AsyncClient, admin_headers: dict):
        assert (await async_client.get("/admin/overview", headers=admin_headers)).status_code == 200

        logout = await async_client.post("/admin/auth/logout", headers=admin_headers)
        assert logout.status_code == 204

        after = await async_client.get("/admin/overview", headers=admin_headers)
        assert after.status_code == 401

    @pytest.mark.asyncio
    async def test_each_device_has_its_own_session(
        self, async_client: AsyncClient, session_maker: SessionMaker
    ):
        await _create_admin(session_maker)
        first: Response = await _login(async_client)
        second: Response = await _login(async_client)
        first_headers = {"Authorization": f"Bearer {first.json()['data']['access_token']}"}
        second_headers = {"Authorization": f"Bearer {second.json()['data']['access_token']}"}

        assert (await async_client.get("/admin/overview", headers=first_headers)).status_code == 200
        assert (
            await async_client.get("/admin/overview", headers=second_headers)
        ).status_code == 200

        assert (
            await async_client.post("/admin/auth/logout", headers=first_headers)
        ).status_code == 204
        assert (await async_client.get("/admin/overview", headers=first_headers)).status_code == 401
        # the other device is still signed in
        assert (
            await async_client.get("/admin/overview", headers=second_headers)
        ).status_code == 200

    @pytest.mark.asyncio
    async def test_deactivated_admin_loses_access(
        self, async_client: AsyncClient, session_maker: SessionMaker, admin_headers: dict
    ):
        me: Response = await async_client.get("/admin/auth/me", headers=admin_headers)
        admin_id: UUID = UUID(me.json()["data"]["id"])

        async with session_maker() as session:
            admin = await session.get(Admin, admin_id)
            admin.is_active = False
            await session.commit()

        res: Response = await async_client.get("/admin/overview", headers=admin_headers)
        assert res.status_code == 401


class TestAdminOverview:
    @pytest.mark.asyncio
    async def test_counts_everything(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        admin_headers: dict,
        session_maker: SessionMaker,
    ):
        merchant: UUID = await _merchant(session_maker)
        successful: UUID = await add_transaction(session_maker, merchant)
        await add_transaction(session_maker, merchant, status=TransactionStatus.FAILED)
        await add_dispute(session_maker, merchant, successful)

        res: Response = await async_client.get("/admin/overview", headers=admin_headers)
        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        assert data["total_merchants"] == 1
        assert data["active_merchants"] == 1
        assert data["verified_merchants"] == 1
        assert data["total_transactions"] == 2
        assert data["successful_transactions"] == 1
        assert data["total_disputes"] == 1
        assert data["open_disputes"] == 1
        assert data["trust_states"] == {}


class TestAdminMerchants:
    @pytest.mark.asyncio
    async def test_lists_merchants_with_counts(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        admin_headers: dict,
        session_maker: SessionMaker,
    ):
        merchant: UUID = await _merchant(session_maker)
        transaction: UUID = await add_transaction(session_maker, merchant)
        await add_transaction(session_maker, merchant)
        await add_dispute(session_maker, merchant, transaction)

        res: Response = await async_client.get("/admin/merchants", headers=admin_headers)
        assert res.status_code == 200, res.text
        body: dict = res.json()
        assert body["meta"]["total"] == 1
        item: dict = body["data"][0]
        assert item["id"] == str(merchant)
        assert item["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert item["email"] == SIGN_UP_PAYLOAD["email"]
        assert item["transaction_count"] == 2
        assert item["dispute_count"] == 1
        assert item["trust_state"] is None

        found = await async_client.get("/admin/merchants?search=acme", headers=admin_headers)
        assert found.json()["meta"]["total"] == 1

        missing = await async_client.get("/admin/merchants?search=nobody", headers=admin_headers)
        assert missing.json()["data"] == []
        assert missing.json()["meta"]["total"] == 0

    @pytest.mark.asyncio
    async def test_detail_includes_data_but_not_secrets(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        admin_headers: dict,
        session_maker: SessionMaker,
    ):
        merchant: UUID = await _merchant(session_maker)
        transaction: UUID = await add_transaction(
            session_maker,
            merchant,
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
            customer_email="buyer@example.com",
        )
        dispute: UUID = await add_dispute(session_maker, merchant, transaction)

        async with session_maker() as session:
            session.add(
                TrustProfile(
                    merchant_id=merchant,
                    current_state=TrustState.BUILDING,
                    internal_score=72,
                    reconciliation_rate=80.0,
                    payments_30d=12,
                    days_on_platform=20,
                    public_token="public-token",
                    explanation="Good start.",
                    recommendations=[{"action": "Match more payments"}],
                )
            )
            await session.commit()

        res: Response = await async_client.get(
            f"/admin/merchants/{merchant}", headers=admin_headers
        )
        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        assert data["business_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert data["stats"]["transaction_count"] == 1
        assert data["stats"]["successful_transactions"] == 1
        assert data["stats"]["dispute_count"] == 1
        assert data["stats"]["open_disputes"] == 1
        assert data["recent_transactions"][0]["id"] == str(transaction)
        assert data["recent_disputes"][0]["id"] == str(dispute)
        assert data["recent_disputes"][0]["status"] == DisputeStatus.PENDING
        assert data["trust"]["state"] == TrustState.BUILDING
        assert data["trust"]["explanation"] == "Good start."
        assert data["trust_history"] == []

        text: str = res.text
        assert "paystack_secret_key" not in text
        assert "hashed_password" not in text
        assert "webhook_token" not in text

    @pytest.mark.asyncio
    async def test_detail_not_found(self, async_client: AsyncClient, admin_headers: dict):
        res: Response = await async_client.get(f"/admin/merchants/{uuid4()}", headers=admin_headers)
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
