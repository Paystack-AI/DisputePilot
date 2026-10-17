"""Paystack API client, one instance per merchant secret key.

Built on httpx instead of the paystack sdk: the sdk reads a module level api key on
every call, so with a key per merchant two concurrent calls could run with each
other's key. Here the key belongs to the client instance and goes on each request.

Every endpoint is written once in _PaystackEndpoints and returns whatever _send
returns: a coroutine on AsyncPaystackClient (api) and the response body on
PaystackClient (celery workers). Amounts are in the smallest currency unit (kobo),
the same as the models, so nothing is converted.

Responses are Paystack's envelope as a dict: {"status", "message", "data", "meta"}.
"""

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings

SETTINGS = get_settings()


class PaystackError(Exception):
    """Base for every error the client raises"""

    # true when the same request can succeed later; workers retry these
    retryable: bool = False

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body


class PaystackAuthError(PaystackError):
    """401: the key is wrong, revoked or missing"""


class PaystackNotFoundError(PaystackError):
    """404: no such record for this key"""


class PaystackRequestError(PaystackError):
    """Any other rejection (400, 422, ...): retrying the same request fails again"""


class PaystackUpstreamError(PaystackError):
    """Paystack is down, slow or rate limiting (5xx, 429, network errors, bad json)"""

    retryable = True


def _path(*parts: str | int) -> str:
    # references are merchant controlled, so path segments are always escaped
    return "/" + "/".join(quote(str(part), safe="") for part in parts)


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Drop unset values and format dates the way paystack expects"""
    cleaned: dict[str, Any] = {}

    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, datetime) and value.tzinfo is not None:
            # same instant whatever the session timezone handed back
            value = value.astimezone(UTC)
        if isinstance(value, datetime | date):
            value = value.isoformat()
        cleaned[key] = value
    return cleaned


def _parse(response: httpx.Response) -> dict:
    try:
        body: Any = response.json()
    except ValueError:
        body = None

    status_code: int = response.status_code
    message: str = (
        body.get("message", "") if isinstance(body, dict) else response.text[:200]
    ) or response.reason_phrase

    if status_code == 429 or status_code >= 500 or (response.is_success and body is None):
        raise PaystackUpstreamError(message, status_code, body)
    if status_code == 401:
        raise PaystackAuthError(message, status_code, body)
    if status_code == 404:
        raise PaystackNotFoundError(message, status_code, body)
    if not response.is_success or not isinstance(body, dict) or body.get("status") is not True:
        raise PaystackRequestError(message, status_code, body)

    return body


def _upstream_error(exc: httpx.HTTPError) -> PaystackUpstreamError:
    return PaystackUpstreamError(f"Request to paystack failed: {exc.__class__.__name__}")


class _PaystackEndpoints(ABC):
    def __init__(self, secret_key: str):
        self._headers: dict[str, str] = {"Authorization": f"Bearer {secret_key}"}

    @abstractmethod
    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ):
        raise NotImplementedError

    # transactions

    def list_transactions(
        self,
        *,
        per_page: int = 50,
        page: int = 1,
        from_: datetime | None = None,
        to: datetime | None = None,
        status: str | None = None,
        customer: int | None = None,
    ):
        """GET /transaction: newest first; meta has total, page and pageCount"""
        return self._send(
            "GET",
            "/transaction",
            params=_clean(
                {
                    "perPage": per_page,
                    "page": page,
                    "from": from_,
                    "to": to,
                    "status": status,
                    "customer": customer,
                }
            ),
        )

    def fetch_transaction(self, transaction_id: int):
        """GET /transaction/:id"""
        return self._send("GET", _path("transaction", transaction_id))

    def verify_transaction(self, reference: str):
        """GET /transaction/verify/:reference: the current state of a payment"""
        return self._send("GET", _path("transaction", "verify", reference))

    def transaction_timeline(self, id_or_reference: int | str):
        """GET /transaction/timeline/:id_or_reference: the customer's steps through
        checkout, used as evidence that they completed the payment"""
        return self._send("GET", _path("transaction", "timeline", id_or_reference))

    # disputes

    def list_disputes(
        self,
        *,
        per_page: int = 50,
        page: int = 1,
        from_: datetime | None = None,
        to: datetime | None = None,
        status: str | None = None,
        transaction: int | None = None,
    ):
        """GET /dispute. status: awaiting-merchant-feedback, awaiting-bank-feedback,
        pending or resolved"""
        return self._send(
            "GET",
            "/dispute",
            params=_clean(
                {
                    "perPage": per_page,
                    "page": page,
                    "from": from_,
                    "to": to,
                    "status": status,
                    "transaction": transaction,
                }
            ),
        )

    def fetch_dispute(self, dispute_id: int):
        """GET /dispute/:id"""
        return self._send("GET", _path("dispute", dispute_id))

    def list_transaction_disputes(self, transaction_id: int):
        """GET /dispute/transaction/:id: disputes raised on one payment"""
        return self._send("GET", _path("dispute", "transaction", transaction_id))

    def update_dispute(
        self, dispute_id: int, *, refund_amount: int, uploaded_filename: str | None = None
    ):
        """PUT /dispute/:id"""
        return self._send(
            "PUT",
            _path("dispute", dispute_id),
            json=_clean({"refund_amount": refund_amount, "uploaded_filename": uploaded_filename}),
        )

    def add_dispute_evidence(
        self,
        dispute_id: int,
        *,
        customer_email: str,
        customer_name: str,
        customer_phone: str,
        service_details: str,
        delivery_address: str | None = None,
        delivery_date: date | None = None,
    ):
        """POST /dispute/:id/evidence: data.id is the evidence id resolve_dispute needs"""
        return self._send(
            "POST",
            _path("dispute", dispute_id, "evidence"),
            json=_clean(
                {
                    "customer_email": customer_email,
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "service_details": service_details,
                    "delivery_address": delivery_address,
                    "delivery_date": delivery_date,
                }
            ),
        )

    def get_dispute_upload_url(self, dispute_id: int, *, upload_filename: str):
        """GET /dispute/:id/upload_url: data has signedUrl (PUT the file there with
        upload_to_signed_url) and fileName (pass it as uploaded_filename)"""
        return self._send(
            "GET",
            _path("dispute", dispute_id, "upload_url"),
            params={"upload_filename": upload_filename},
        )

    def resolve_dispute(
        self,
        dispute_id: int,
        *,
        resolution: str,
        message: str,
        refund_amount: int,
        uploaded_filename: str,
        evidence: int | None = None,
    ):
        """PUT /dispute/:id/resolve. resolution: merchant-accepted or declined;
        declining needs the evidence id from add_dispute_evidence"""
        return self._send(
            "PUT",
            _path("dispute", dispute_id, "resolve"),
            json=_clean(
                {
                    "resolution": resolution,
                    "message": message,
                    "refund_amount": refund_amount,
                    "uploaded_filename": uploaded_filename,
                    "evidence": evidence,
                }
            ),
        )


# a pool of live connections to paystack: up to 50 stay open between requests for
# 5 minutes, so most calls skip the tcp + tls handshake
POOL_LIMITS = httpx.Limits(
    max_connections=100, max_keepalive_connections=50, keepalive_expiry=60 * 5
)


def create_async_http_client() -> httpx.AsyncClient:
    """Shared by every AsyncPaystackClient so connections are reused across merchants"""
    return httpx.AsyncClient(
        base_url=SETTINGS.PAYSTACK_BASE_URL, timeout=SETTINGS.PAYSTACK_TIMEOUT, limits=POOL_LIMITS
    )


def create_http_client() -> httpx.Client:
    """Shared by every PaystackClient in a worker process"""
    return httpx.Client(
        base_url=SETTINGS.PAYSTACK_BASE_URL, timeout=SETTINGS.PAYSTACK_TIMEOUT, limits=POOL_LIMITS
    )


class AsyncPaystackClient(_PaystackEndpoints):
    def __init__(self, secret_key: str, http_client: httpx.AsyncClient):
        super().__init__(secret_key)
        self._http = http_client

    async def _send(self, method, path, *, params=None, json=None) -> dict:
        try:
            response = await self._http.request(
                method, path, params=params, json=json, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise _upstream_error(exc) from exc
        return _parse(response)

    async def upload_to_signed_url(self, signed_url: str, content: bytes, content_type: str):
        """PUT a dispute file to the url from get_dispute_upload_url. The url is
        pre-signed storage, so the paystack key is not sent"""
        try:
            response = await self._http.put(
                signed_url, content=content, headers={"Content-Type": content_type}
            )
        except httpx.HTTPError as exc:
            raise _upstream_error(exc) from exc
        if not response.is_success:
            error = PaystackUpstreamError if response.status_code >= 500 else PaystackRequestError
            raise error("Dispute file upload failed", response.status_code)


class PaystackClient(_PaystackEndpoints):
    def __init__(self, secret_key: str, http_client: httpx.Client):
        super().__init__(secret_key)
        self._http = http_client

    def _send(self, method, path, *, params=None, json=None) -> dict:
        try:
            response = self._http.request(
                method, path, params=params, json=json, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise _upstream_error(exc) from exc
        return _parse(response)

    def upload_to_signed_url(self, signed_url: str, content: bytes, content_type: str):
        """PUT a dispute file to the url from get_dispute_upload_url. The url is
        pre-signed storage, so the paystack key is not sent"""
        try:
            response = self._http.put(
                signed_url, content=content, headers={"Content-Type": content_type}
            )
        except httpx.HTTPError as exc:
            raise _upstream_error(exc) from exc
        if not response.is_success:
            error = PaystackUpstreamError if response.status_code >= 500 else PaystackRequestError
            raise error("Dispute file upload failed", response.status_code)
