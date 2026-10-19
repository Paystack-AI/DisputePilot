from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient, Response
from kombu.exceptions import OperationalError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import OnboardingStep
from app.api.models.merchant_onboarding import MerchantOnboarding
from app.api.models.merchants import Merchant
from app.worker.tasks.transaction_sync import INITIAL_SYNC_PRIORITY
from tests.conftest import SIGN_UP_PAYLOAD
from tests.test_paystack import TEST_SECRET_KEY


async def _connect(async_client: AsyncClient, headers: dict) -> Response:
    return await async_client.post(
        "/auth/paystack/connect", json={"secret_key": TEST_SECRET_KEY}, headers=headers
    )


async def _configure(async_client: AsyncClient, headers: dict, payload: dict) -> Response:
    return await async_client.post("/onboarding/notifications", json=payload, headers=headers)


async def _set_step(session_maker: async_sessionmaker[AsyncSession], step: OnboardingStep):
    """Move onboarding forward where a background task would (the sync is still a TODO)"""
    async with session_maker() as session:
        merchant_id = (
            await session.execute(
                select(Merchant.id).where(Merchant.email == SIGN_UP_PAYLOAD["email"])
            )
        ).scalar_one()
        await session.execute(
            update(MerchantOnboarding)
            .where(MerchantOnboarding.merchant_id == merchant_id)
            .values(current_step=step)
        )
        await session.commit()


class TestGetOnboarding:
    @pytest.mark.asyncio
    async def test_new_merchant(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/onboarding", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["data"] == {
            "next_step": "connect_paystack",
            "completed": False,
            "initial_sync_status": "not_started",
            "initial_sync_total": None,
            "initial_sync_processed": 0,
            "first_reconciliation_skipped": False,
            "completed_at": None,
        }

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await async_client.get("/onboarding")

        assert res.status_code == 401


class TestConfigureNotifications:
    @pytest.mark.asyncio
    async def test_configure(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers)

        res: Response = await _configure(async_client, auth_headers, {"notification_email": False})
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["next_step"] == "initial_sync"
        assert data["initial_sync_status"] == "in_progress"

        res = await async_client.get("/settings", headers=auth_headers)
        assert res.json()["data"]["notification_email"] is False

    @pytest.mark.asyncio
    async def test_queues_initial_sync(
        self, async_client: AsyncClient, auth_headers: dict, queued_syncs: MagicMock
    ):
        await _connect(async_client, auth_headers)
        await _configure(async_client, auth_headers, {})

        queued_syncs.assert_called_once()
        assert queued_syncs.call_args.kwargs["kwargs"]["initial"] is True
        assert queued_syncs.call_args.kwargs["priority"] == INITIAL_SYNC_PRIORITY

    @pytest.mark.asyncio
    async def test_broker_unavailable_fails_the_sync(
        self, async_client: AsyncClient, auth_headers: dict, queued_syncs: MagicMock
    ):
        await _connect(async_client, auth_headers)
        queued_syncs.side_effect = OperationalError("broker unavailable")

        res: Response = await _configure(async_client, auth_headers, {})
        assert res.status_code == 500

        # not left showing in progress when nothing will run it
        res = await async_client.get("/onboarding", headers=auth_headers)
        assert res.json()["data"]["initial_sync_status"] == "failed"

    @pytest.mark.asyncio
    async def test_empty_body_keeps_defaults(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers)

        res: Response = await _configure(async_client, auth_headers, {})
        assert res.status_code == 200
        assert res.json()["data"]["next_step"] == "initial_sync"

        res = await async_client.get("/settings", headers=auth_headers)
        assert res.json()["data"]["notification_email"] is True

    @pytest.mark.asyncio
    async def test_before_connecting(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _configure(async_client, auth_headers, {})
        error: dict = res.json()["error"]

        assert res.status_code == 409
        assert error["code"] == "ONBOARDING_STEP_MISMATCH"
        assert error["details"] == {"current_step": "connect_paystack"}

    @pytest.mark.asyncio
    async def test_submitted_twice(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers)
        await _configure(async_client, auth_headers, {})

        # e.g. a resumed tab submitting again must not start a second sync
        res: Response = await _configure(async_client, auth_headers, {})

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"current_step": "initial_sync"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"notification_email": None},
            # whatsapp alerts are not offered (pending meta business verification)
            {"notification_whatsapp": "+2348012345678"},
            # only notification preferences belong to this step
            {"timezone": "Africa/Lagos"},
        ],
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, payload: dict
    ):
        await _connect(async_client, auth_headers)

        res: Response = await _configure(async_client, auth_headers, payload)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"


class TestSkipFirstReconciliation:
    @pytest.mark.asyncio
    async def test_skip(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: async_sessionmaker[AsyncSession],
    ):
        await _set_step(session_maker, OnboardingStep.FIRST_RECONCILIATION)

        res: Response = await async_client.post(
            "/onboarding/first-reconciliation/skip", headers=auth_headers
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["next_step"] == "completed"
        assert data["completed"] is True
        assert data["first_reconciliation_skipped"] is True
        assert data["completed_at"] is not None

        res = await async_client.get("/auth/me", headers=auth_headers)
        assert res.json()["data"]["onboarding"] == {"completed": True, "next_step": "completed"}

    @pytest.mark.asyncio
    async def test_skip_during_sync(self, async_client: AsyncClient, auth_headers: dict):
        await _connect(async_client, auth_headers)
        await _configure(async_client, auth_headers, {})

        res: Response = await async_client.post(
            "/onboarding/first-reconciliation/skip", headers=auth_headers
        )

        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"current_step": "initial_sync"}


class TestKeyRotationDuringOnboarding:
    @pytest.mark.asyncio
    async def test_reconnect_on_notifications_step(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        await _connect(async_client, auth_headers)
        await _connect(async_client, auth_headers)

        res: Response = await async_client.get("/onboarding", headers=auth_headers)
        assert res.json()["data"]["next_step"] == "configure_notifications"
        assert res.json()["data"]["initial_sync_status"] == "not_started"
