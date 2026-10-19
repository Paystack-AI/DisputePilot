from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.api.models.enums import OrderStatus, ReconciliationStatus
from app.api.models.files import StoredFile
from app.api.models.merchants import Merchant
from app.worker.tasks import files as file_tasks
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_transaction, merchant_id, set_order, sign_in_merchant
from tests.test_uploads import uploaded_ids

SessionMaker = async_sessionmaker[AsyncSession]
DELIVERED: str = "2026-10-18T14:00:00Z"


async def _order(async_client: AsyncClient, headers: dict, amount: int = 4500000) -> dict:
    res: Response = await async_client.post("/orders", json={"amount": amount}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _payload(order_id: str, **extra) -> dict:
    return {"order_id": order_id, "type": "delivery", "delivery_date": DELIVERED, **extra}


async def _create(async_client: AsyncClient, headers: dict, payload: dict) -> Response:
    return await async_client.post("/fulfillments", json=payload, headers=headers)


class TestCreateFulfillment:
    @pytest.mark.asyncio
    async def test_create_with_photos(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers, count=2)

        res: Response = await _create(
            async_client,
            auth_headers,
            _payload(
                order["id"],
                tracking_number="GIG-0012",
                recipient_name="Amina Yusuf",
                notes="Left with the gate man",
                file_ids=file_ids,
            ),
        )
        data: dict = res.json()["data"]

        assert res.status_code == 201
        assert data["order_id"] == order["id"]
        assert data["type"] == "delivery"
        assert data["tracking_number"] == "GIG-0012"
        assert data["transaction_id"] is None
        assert [f["id"] for f in data["files"]] == file_ids
        assert data["files"][0]["content_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_paid_order_becomes_fulfilled(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        paid: dict = await _order(async_client, auth_headers)
        pending: dict = await _order(async_client, auth_headers)
        await set_order(session_maker, paid["id"], status=OrderStatus.PAID)

        await _create(async_client, auth_headers, _payload(paid["id"]))
        await _create(async_client, auth_headers, _payload(pending["id"]))

        statuses = {}
        for order in (paid, pending):
            res = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)
            statuses[order["id"]] = res.json()["data"]["status"]
        assert statuses == {paid["id"]: "fulfilled", pending["id"]: "pending"}

    @pytest.mark.asyncio
    async def test_cancelled_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        await set_order(session_maker, order["id"], status=OrderStatus.CANCELLED)

        res: Response = await _create(async_client, auth_headers, _payload(order["id"]))

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "ORDER_STATUS_TRANSITION"

    @pytest.mark.asyncio
    async def test_defaults_to_the_orders_linked_payment(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        order: dict = await _order(async_client, auth_headers)
        transaction_id: UUID = await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )

        res: Response = await _create(async_client, auth_headers, _payload(order["id"]))

        assert res.json()["data"]["transaction_id"] == str(transaction_id)

    @pytest.mark.asyncio
    async def test_payment_of_another_order(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        order: dict = await _order(async_client, auth_headers)
        other_order: dict = await _order(async_client, auth_headers)
        transaction_id: UUID = await add_transaction(
            session_maker, merchant, order_id=UUID(other_order["id"])
        )

        res: Response = await _create(
            async_client,
            auth_headers,
            _payload(order["id"], transaction_id=str(transaction_id)),
        )

        assert res.status_code == 422
        assert "transaction_id" in res.json()["error"]["details"]

    @pytest.mark.asyncio
    async def test_file_already_attached(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        await _create(async_client, auth_headers, _payload(order["id"], file_ids=file_ids))

        res: Response = await _create(
            async_client, auth_headers, _payload(order["id"], file_ids=file_ids)
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "FILE_ALREADY_ATTACHED"
        assert res.json()["error"]["details"] == {"file_id": file_ids[0]}

    @pytest.mark.asyncio
    async def test_other_merchants_records(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )
        other_order: dict = await _order(async_client, other_headers)

        # another merchant's order
        res: Response = await _create(async_client, other_headers, _payload(order["id"]))
        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Order not found."

        # another merchant's photo
        res = await _create(
            async_client, other_headers, _payload(other_order["id"], file_ids=file_ids)
        )
        assert res.status_code == 404
        assert res.json()["error"]["message"] == "File not found."

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "extra",
        [
            {"type": "teleported"},
            {"delivery_date": "yesterday"},
            {"file_ids": ["0192f0c1-0000-7000-8000-000000000000"] * 2},  # duplicates
            {"file_ids": ["0192f0c1-0000-7000-8000-00000000000a"] * 11},  # too many
            {"proof_photo_url": "https://example.com/a.jpg"},  # replaced by file_ids
        ],
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, extra: dict
    ):
        order: dict = await _order(async_client, auth_headers)

        res: Response = await _create(async_client, auth_headers, _payload(order["id"], **extra))

        assert res.status_code == 422


class TestIdempotencyKey:
    @pytest.mark.asyncio
    async def test_retry_returns_the_first_fulfillment(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        headers: dict = {**auth_headers, "Idempotency-Key": "save-7f3c"}
        payload: dict = _payload(order["id"], file_ids=file_ids)

        first: Response = await _create(async_client, headers, payload)
        # e.g. the response was lost and the app retried
        retry: Response = await _create(async_client, headers, payload)

        assert first.status_code == retry.status_code == 201
        assert retry.json()["data"] == first.json()["data"]
        listed = await async_client.get("/fulfillments", headers=auth_headers)
        assert listed.json()["meta"]["total"] == 1

    @pytest.mark.asyncio
    async def test_key_reused_for_another_order(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        order: dict = await _order(async_client, auth_headers)
        other_order: dict = await _order(async_client, auth_headers)
        headers: dict = {**auth_headers, "Idempotency-Key": "save-7f3c"}
        await _create(async_client, headers, _payload(order["id"]))

        res: Response = await _create(async_client, headers, _payload(other_order["id"]))

        assert res.status_code == 422
        assert "Idempotency-Key" in res.json()["error"]["details"]

    @pytest.mark.asyncio
    async def test_keys_are_per_merchant(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )
        other_order: dict = await _order(async_client, other_headers)

        await _create(
            async_client, {**auth_headers, "Idempotency-Key": "k1"}, _payload(order["id"])
        )
        res: Response = await _create(
            async_client,
            {**other_headers, "Idempotency-Key": "k1"},
            _payload(other_order["id"]),
        )

        assert res.status_code == 201
        assert res.json()["data"]["order_id"] == other_order["id"]

    @pytest.mark.asyncio
    async def test_without_a_key_each_create_counts(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        order: dict = await _order(async_client, auth_headers)

        await _create(async_client, auth_headers, _payload(order["id"]))
        await _create(async_client, auth_headers, _payload(order["id"]))

        listed = await async_client.get("/fulfillments", headers=auth_headers)
        assert listed.json()["meta"]["total"] == 2


class TestUpdateFulfillment:
    @pytest.mark.asyncio
    async def test_update_details_and_replace_photos(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        order: dict = await _order(async_client, auth_headers)
        first, second, third = await uploaded_ids(async_client, auth_headers, count=3)
        created: Response = await _create(
            async_client, auth_headers, _payload(order["id"], file_ids=[first, second])
        )
        fulfillment_id: str = created.json()["data"]["id"]

        res: Response = await async_client.patch(
            f"/fulfillments/{fulfillment_id}",
            json={"tracking_number": "GIG-0099", "file_ids": [second, third]},
            headers=auth_headers,
        )
        data: dict = res.json()["data"]

        assert res.status_code == 200
        assert data["tracking_number"] == "GIG-0099"
        assert sorted(f["id"] for f in data["files"]) == sorted([second, third])
        assert data["updated_at"] is not None

        # the removed photo is unattached again (the cleanup task deletes it later)
        async with session_maker() as session:
            removed: StoredFile = await session.get(StoredFile, UUID(first))
        assert removed.fulfillment_id is None

    @pytest.mark.asyncio
    async def test_unchanged_fields_stay(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        created: Response = await _create(
            async_client,
            auth_headers,
            _payload(order["id"], recipient_name="Amina", file_ids=file_ids),
        )

        res: Response = await async_client.patch(
            f"/fulfillments/{created.json()['data']['id']}",
            json={"notes": "Signed for"},
            headers=auth_headers,
        )

        assert res.json()["data"]["recipient_name"] == "Amina"
        assert [f["id"] for f in res.json()["data"]["files"]] == file_ids

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload", [{"type": None}, {"delivery_date": None}, {"file_ids": None}, {"order_id": 1}]
    )
    async def test_invalid_payload(
        self, async_client: AsyncClient, auth_headers: dict, payload: dict
    ):
        order: dict = await _order(async_client, auth_headers)
        created: Response = await _create(async_client, auth_headers, _payload(order["id"]))

        res: Response = await async_client.patch(
            f"/fulfillments/{created.json()['data']['id']}", json=payload, headers=auth_headers
        )

        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_other_merchants_fulfillment(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        created: Response = await _create(async_client, auth_headers, _payload(order["id"]))
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.patch(
            f"/fulfillments/{created.json()['data']['id']}",
            json={"notes": "x"},
            headers=other_headers,
        )

        assert res.status_code == 404


class TestReadFulfillments:
    @pytest.mark.asyncio
    async def test_get(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        created: Response = await _create(
            async_client, auth_headers, _payload(order["id"], file_ids=file_ids)
        )

        res: Response = await async_client.get(
            f"/fulfillments/{created.json()['data']['id']}", headers=auth_headers
        )

        assert res.status_code == 200
        assert res.json()["data"] == created.json()["data"]

    @pytest.mark.asyncio
    async def test_list_with_filters(self, async_client: AsyncClient, auth_headers: dict):
        first_order: dict = await _order(async_client, auth_headers)
        second_order: dict = await _order(async_client, auth_headers)
        file_ids: list[str] = await uploaded_ids(async_client, auth_headers)
        await _create(async_client, auth_headers, _payload(first_order["id"], file_ids=file_ids))
        await _create(
            async_client,
            auth_headers,
            {**_payload(second_order["id"]), "delivery_date": "2026-10-17T09:00:00Z"},
        )

        res: Response = await async_client.get("/fulfillments", headers=auth_headers)
        body: dict = res.json()
        assert body["meta"]["total"] == 2
        # newest delivery first, each with its photos
        assert [f["order_id"] for f in body["data"]] == [first_order["id"], second_order["id"]]
        assert [f["id"] for f in body["data"][0]["files"]] == file_ids
        assert body["data"][1]["files"] == []

        res = await async_client.get(
            "/fulfillments", params={"order_id": second_order["id"]}, headers=auth_headers
        )
        assert [f["order_id"] for f in res.json()["data"]] == [second_order["id"]]

    @pytest.mark.asyncio
    async def test_order_detail_lists_it(self, async_client: AsyncClient, auth_headers: dict):
        order: dict = await _order(async_client, auth_headers)
        created: Response = await _create(async_client, auth_headers, _payload(order["id"]))

        res: Response = await async_client.get(f"/orders/{order['id']}", headers=auth_headers)

        assert [f["id"] for f in res.json()["data"]["fulfillments"]] == [
            created.json()["data"]["id"]
        ]


class FakeMinioClient:
    def __init__(self):
        self.removed: list[str] = []

    def remove_object(self, bucket_name: str, object_name: str):
        self.removed.append(object_name)


class TestUnattachedCleanup:
    def _file(self, session: Session, merchant: Merchant, age: timedelta, **links) -> StoredFile:
        stored_file = StoredFile(
            merchant_id=merchant.id,
            object_name=f"merchants/{merchant.id}/files/{age.total_seconds()}-{len(links)}.jpg",
            file_name="photo.jpg",
            content_type="image/jpeg",
            size=10,
            width=1,
            height=1,
            created_at=datetime.now(UTC) - age,
            **links,
        )
        session.add(stored_file)
        session.flush()
        return stored_file

    def test_deletes_only_old_unattached_files(self, sync_db: Session):
        merchant = Merchant(email="cleanup@example.com", business_name="Cleanup Store")
        sync_db.add(merchant)
        sync_db.flush()

        old = self._file(sync_db, merchant, timedelta(hours=30))
        recent = self._file(sync_db, merchant, timedelta(hours=1))
        sync_db.commit()

        client = FakeMinioClient()

        @contextmanager
        def session_factory():
            yield sync_db

        with (
            patch.object(file_tasks, "sync_session", session_factory),
            patch.object(file_tasks, "_get_storage", lambda: type("S", (), {"client": client})),
        ):
            removed: int = file_tasks.delete_unattached_files()

        remaining = set(sync_db.scalars(select(StoredFile.id)))
        assert removed == 1
        assert client.removed == [old.object_name]
        assert remaining == {recent.id}
