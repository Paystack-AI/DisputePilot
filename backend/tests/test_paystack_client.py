import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.api.clients.paystack import (
    AsyncPaystackClient,
    PaystackAuthError,
    PaystackClient,
    PaystackNotFoundError,
    PaystackRequestError,
    PaystackUpstreamError,
)

BASE_URL: str = "https://api.paystack.co"
KEY_A: str = "sk_test_merchanta"  # pragma: allowlist secret
KEY_B: str = "sk_test_merchantb"  # pragma: allowlist secret
OK: dict = {"status": True, "message": "ok", "data": {"id": 1}, "meta": {}}


class Recorder:
    def __init__(self, status_code: int = 200, body: dict | None = OK, raw: bytes | None = None):
        self.requests: list[httpx.Request] = []
        self._status_code = status_code
        self._body = body
        self._raw = raw

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raw is not None:
            return httpx.Response(self._status_code, content=self._raw)
        return httpx.Response(self._status_code, json=self._body)


def _async_http(recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(recorder), base_url=BASE_URL)


class TestRequests:
    @pytest.mark.asyncio
    async def test_each_client_sends_its_own_key(self):
        recorder = Recorder()
        async with _async_http(recorder) as http:
            # one shared connection pool, two merchants
            await AsyncPaystackClient(KEY_A, http).fetch_dispute(1)
            await AsyncPaystackClient(KEY_B, http).fetch_dispute(2)

        assert [r.headers["Authorization"] for r in recorder.requests] == [
            f"Bearer {KEY_A}",
            f"Bearer {KEY_B}",
        ]

    @pytest.mark.asyncio
    async def test_list_params_drop_unset_and_format_dates(self):
        recorder = Recorder()
        async with _async_http(recorder) as http:
            await AsyncPaystackClient(KEY_A, http).list_disputes(
                per_page=100, from_=datetime(2026, 9, 1, tzinfo=UTC), status="pending"
            )

        (request,) = recorder.requests
        assert request.url.path == "/dispute"
        assert dict(request.url.params) == {
            "perPage": "100",
            "page": "1",
            "from": "2026-09-01T00:00:00+00:00",
            "status": "pending",
        }

    @pytest.mark.asyncio
    async def test_reference_is_escaped_in_the_path(self):
        recorder = Recorder()
        async with _async_http(recorder) as http:
            await AsyncPaystackClient(KEY_A, http).verify_transaction("order/12?x=1")

        (request,) = recorder.requests
        assert request.url.raw_path == b"/transaction/verify/order%2F12%3Fx%3D1"

    @pytest.mark.asyncio
    async def test_add_evidence_body(self):
        recorder = Recorder()
        async with _async_http(recorder) as http:
            await AsyncPaystackClient(KEY_A, http).add_dispute_evidence(
                7,
                customer_email="ada@example.com",
                customer_name="Ada",
                customer_phone="08012345678",
                service_details="Two shirts, delivered",
                delivery_date=date(2026, 9, 3),
            )

        (request,) = recorder.requests
        assert (request.method, request.url.path) == ("POST", "/dispute/7/evidence")
        assert json.loads(request.content) == {
            "customer_email": "ada@example.com",
            "customer_name": "Ada",
            "customer_phone": "08012345678",
            "service_details": "Two shirts, delivered",
            "delivery_date": "2026-09-03",
        }

    @pytest.mark.asyncio
    async def test_resolve_body(self):
        recorder = Recorder()
        async with _async_http(recorder) as http:
            await AsyncPaystackClient(KEY_A, http).resolve_dispute(
                7,
                resolution="declined",
                message="Delivered, signed for",
                refund_amount=0,
                uploaded_filename="evidence.pdf",
                evidence=42,
            )

        (request,) = recorder.requests
        assert (request.method, request.url.path) == ("PUT", "/dispute/7/resolve")
        assert json.loads(request.content)["evidence"] == 42

    @pytest.mark.asyncio
    async def test_signed_url_upload_does_not_send_the_key(self):
        recorder = Recorder(body={})
        async with _async_http(recorder) as http:
            await AsyncPaystackClient(KEY_A, http).upload_to_signed_url(
                "https://files.example.com/upload?sig=abc", b"%PDF", "application/pdf"
            )

        (request,) = recorder.requests
        assert request.url.host == "files.example.com"
        assert "Authorization" not in request.headers
        assert request.content == b"%PDF"

    def test_sync_client(self):
        recorder = Recorder()
        with httpx.Client(transport=httpx.MockTransport(recorder), base_url=BASE_URL) as http:
            body: dict = PaystackClient(KEY_A, http).list_transactions(per_page=1)

        assert body == OK
        assert recorder.requests[0].headers["Authorization"] == f"Bearer {KEY_A}"


class TestErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "body", "error"),
        [
            (401, {"status": False, "message": "Invalid key"}, PaystackAuthError),
            (404, {"status": False, "message": "Dispute not found"}, PaystackNotFoundError),
            (400, {"status": False, "message": "Invalid refund amount"}, PaystackRequestError),
            # paystack can answer 200 with status false
            (200, {"status": False, "message": "Rejected"}, PaystackRequestError),
            (429, {"status": False, "message": "Too many requests"}, PaystackUpstreamError),
            (500, {"status": False, "message": "Server error"}, PaystackUpstreamError),
        ],
    )
    async def test_status_mapping(self, status_code: int, body: dict, error: type):
        async with _async_http(Recorder(status_code, body)) as http:
            with pytest.raises(error) as raised:
                await AsyncPaystackClient(KEY_A, http).fetch_dispute(1)

        assert raised.value.status_code == status_code
        assert raised.value.message == body["message"]
        assert raised.value.retryable is (error is PaystackUpstreamError)

    @pytest.mark.asyncio
    async def test_non_json_success_is_upstream(self):
        async with _async_http(Recorder(200, raw=b"<html>gateway</html>")) as http:
            with pytest.raises(PaystackUpstreamError):
                await AsyncPaystackClient(KEY_A, http).fetch_dispute(1)

    @pytest.mark.asyncio
    async def test_network_error_is_upstream(self):
        def fail(request: httpx.Request):
            raise httpx.ConnectTimeout("timed out", request=request)

        async with _async_http(fail) as http:
            with pytest.raises(PaystackUpstreamError) as raised:
                await AsyncPaystackClient(KEY_A, http).fetch_dispute(1)

        # the key never ends up in an error message
        assert KEY_A not in raised.value.message
