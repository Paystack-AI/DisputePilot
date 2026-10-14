import pytest
from httpx import AsyncClient, Response

from tests.test_paystack import TEST_SECRET_KEY


async def _patch(async_client: AsyncClient, headers: dict, payload: dict) -> Response:
    return await async_client.patch("/settings", json=payload, headers=headers)


class TestGetSettings:
    @pytest.mark.asyncio
    async def test_defaults(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/settings", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["data"] == {
            "notification_whatsapp": None,
            "notification_email": True,
            "auto_reconciliation_tier1": True,
            "default_reconciliation_range": 1,
            "trust_public_enabled": False,
            "trust_widget_enabled": False,
            "timezone": "UTC",
            "default_currency": "NGN",
            "updated_at": None,
        }

    @pytest.mark.asyncio
    async def test_reflects_updates(self, async_client: AsyncClient, auth_headers: dict):
        await _patch(async_client, auth_headers, {"timezone": "Africa/Accra"})

        res: Response = await async_client.get("/settings", headers=auth_headers)

        assert res.json()["data"]["timezone"] == "Africa/Accra"
        assert res.json()["data"]["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await async_client.get("/settings")

        assert res.status_code == 401


class TestWhatsappNumber:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "number, stored",
        [
            ("+2348031234567", "+2348031234567"),
            # spacing and punctuation are normalised to E.164
            ("+234 803 123 4567", "+2348031234567"),
            ("+234-803-123-4567", "+2348031234567"),
            ("+233241234567", "+233241234567"),
            ("+254712345678", "+254712345678"),
            ("+27821234567", "+27821234567"),
        ],
    )
    async def test_valid_numbers(
        self, async_client: AsyncClient, auth_headers: dict, number: str, stored: str
    ):
        res: Response = await _patch(async_client, auth_headers, {"notification_whatsapp": number})

        assert res.status_code == 200
        assert res.json()["data"]["notification_whatsapp"] == stored

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "number",
        [
            "08031234567",  # no country code
            "+2341234",  # too short to exist
            "+442071838750",  # london landline, can not receive whatsapp
            "not a number",
        ],
    )
    async def test_invalid_numbers(
        self, async_client: AsyncClient, auth_headers: dict, number: str
    ):
        res: Response = await _patch(async_client, auth_headers, {"notification_whatsapp": number})

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_notification_preferences_after_onboarding(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        await async_client.post(
            "/auth/paystack/connect", json={"secret_key": TEST_SECRET_KEY}, headers=auth_headers
        )
        await async_client.post("/onboarding/notifications", json={}, headers=auth_headers)

        # once the onboarding step is done, preferences are still changed here
        res: Response = await _patch(
            async_client,
            auth_headers,
            {"notification_whatsapp": "+2348031234567", "notification_email": False},
        )

        assert res.status_code == 200
        assert res.json()["data"]["notification_whatsapp"] == "+2348031234567"
        assert res.json()["data"]["notification_email"] is False

    @pytest.mark.asyncio
    async def test_update(self, async_client: AsyncClient, auth_headers: dict):
        payload: dict = {
            "notification_whatsapp": "+2348012345678",
            "notification_email": False,
            "auto_reconciliation_tier1": False,
            "default_reconciliation_range": 7,
            "trust_public_enabled": True,
            "trust_widget_enabled": True,
            "timezone": "Africa/Lagos",
            "default_currency": "GHS",
        }
        res: Response = await _patch(async_client, auth_headers, payload)
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert {key: data[key] for key in payload} == payload
        assert data["updated_at"] is not None

        res = await async_client.get("/auth/me", headers=auth_headers)
        assert res.json()["data"]["timezone"] == "Africa/Lagos"
        assert res.json()["data"]["default_currency"] == "GHS"

    @pytest.mark.asyncio
    async def test_partial_update(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await _patch(
            async_client, auth_headers, {"default_reconciliation_range": 3}
        )
        data: dict = res.json()["data"]

        assert data["default_reconciliation_range"] == 3
        # defaults untouched
        assert data["notification_email"] is True
        assert data["timezone"] == "UTC"
        assert data["default_currency"] == "NGN"

    @pytest.mark.asyncio
    async def test_null_whatsapp_disables_it(self, async_client: AsyncClient, auth_headers: dict):
        await _patch(async_client, auth_headers, {"notification_whatsapp": "+2348012345678"})

        res: Response = await _patch(async_client, auth_headers, {"notification_whatsapp": None})

        assert res.status_code == 200
        assert res.json()["data"]["notification_whatsapp"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"notification_email": None},
            {"timezone": None},
            {"timezone": "Mars/Olympus_Mons"},
            {"notification_whatsapp": "08012345678"},
            {"default_reconciliation_range": 0},
            {"default_reconciliation_range": 91},
            {"default_currency": "USDT"},
            {"unknown_setting": True},
        ],
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, payload: dict
    ):
        res: Response = await _patch(async_client, auth_headers, payload)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await _patch(async_client, {}, {"notification_email": False})

        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_does_not_advance_onboarding(self, async_client: AsyncClient, auth_headers: dict):
        await async_client.post(
            "/auth/paystack/connect", json={"secret_key": TEST_SECRET_KEY}, headers=auth_headers
        )

        # only the dedicated onboarding endpoint completes the notifications step
        await _patch(async_client, auth_headers, {"notification_whatsapp": "+2348012345678"})

        res: Response = await async_client.get("/auth/me", headers=auth_headers)
        assert res.json()["data"]["onboarding"]["next_step"] == "configure_notifications"
