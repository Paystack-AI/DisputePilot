from io import BytesIO

import pillow_heif
import pytest
from httpx import AsyncClient, Response
from PIL import Image

from app.api.routers import uploads as uploads_router
from app.core.config import get_settings
from tests.conftest import FakeStorage
from tests.factories import sign_in_merchant

SETTINGS = get_settings()

GPS_IFD: int = 0x8825
ORIENTATION: int = 0x0112


def image_bytes(
    image_format: str = "JPEG",
    size: tuple[int, int] = (40, 20),
    exif: Image.Exif | None = None,
) -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", size, (200, 30, 30))
    options: dict = {"exif": exif} if exif is not None else {}
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def photo_with_location() -> bytes:
    """A phone photo: GPS coordinates, and an orientation tag saying it is rotated"""
    exif = Image.Exif()
    exif[ORIENTATION] = 6  # rotate 90 degrees clockwise to display
    exif[0x010F] = "PhoneMaker"  # camera make
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (6.0, 27.0, 0.0), 3: "E", 4: (3.0, 23.0, 0.0)})
    return image_bytes(size=(40, 20), exif=exif)


def heic_bytes() -> bytes:
    buffer = BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (32, 16), (10, 120, 200))).save(buffer)
    return buffer.getvalue()


async def _upload(async_client: AsyncClient, headers: dict, files: list[tuple]) -> Response:
    return await async_client.post(
        "/uploads", files=[("files", file) for file in files], headers=headers
    )


async def uploaded_ids(async_client: AsyncClient, headers: dict, count: int = 1) -> list[str]:
    files = [(f"photo-{n}.jpg", image_bytes(), "image/jpeg") for n in range(count)]
    res: Response = await _upload(async_client, headers, files)
    assert res.status_code == 201, res.text
    return [file["id"] for file in res.json()["data"]["files"]]


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        res: Response = await _upload(
            async_client,
            auth_headers,
            [
                ("front.jpg", image_bytes(), "image/jpeg"),
                ("label.png", image_bytes("PNG", (10, 12)), "image/png"),
            ],
        )
        files: list[dict] = res.json()["data"]["files"]

        assert res.status_code == 201
        # same order as sent, so the client can map its files to the ids
        assert [f["file_name"] for f in files] == ["front.jpg", "label.png"]
        assert [f["content_type"] for f in files] == ["image/jpeg", "image/png"]
        assert (files[1]["width"], files[1]["height"]) == (10, 12)
        # the storage location never leaves the api
        assert "object_name" not in files[0]
        assert len(storage.objects) == 2
        assert all(name.startswith("merchants/") and "/files/" in name for name in storage.objects)

    @pytest.mark.asyncio
    async def test_type_comes_from_the_content(self, async_client: AsyncClient, auth_headers: dict):
        # a png sent with a jpeg name and content type is stored as what it is
        res: Response = await _upload(
            async_client, auth_headers, [("photo.jpg", image_bytes("PNG"), "image/jpeg")]
        )

        assert res.json()["data"]["files"][0]["content_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_metadata_is_stripped_and_photo_kept_upright(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        res: Response = await _upload(
            async_client, auth_headers, [("delivery.jpg", photo_with_location(), "image/jpeg")]
        )
        stored = Image.open(BytesIO(next(iter(storage.objects.values()))[0]))
        file: dict = res.json()["data"]["files"][0]

        # rotated by its orientation tag before the tag was dropped
        assert (stored.width, stored.height) == (20, 40)
        assert (file["width"], file["height"]) == (20, 40)
        # no location, camera or orientation left
        exif: Image.Exif = stored.getexif()
        assert exif.get_ifd(GPS_IFD) == {}
        assert ORIENTATION not in exif
        assert 0x010F not in exif

    @pytest.mark.asyncio
    async def test_heic_is_stored_as_jpeg(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        res: Response = await _upload(
            async_client, auth_headers, [("IMG_0001.HEIC", heic_bytes(), "image/heic")]
        )
        file: dict = res.json()["data"]["files"][0]

        assert res.status_code == 201
        assert file["content_type"] == "image/jpeg"
        assert file["file_name"] == "IMG_0001.HEIC"
        assert next(iter(storage.objects)).endswith(".jpg")
        assert Image.open(BytesIO(next(iter(storage.objects.values()))[0])).format == "JPEG"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        [
            b"%PDF-1.7 not an image",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,  # png signature, then garbage
            image_bytes("GIF"),  # a real image, but not an allowed format
            b"",
        ],
    )
    async def test_rejects_non_images(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        storage: FakeStorage,
        content: bytes,
    ):
        res: Response = await _upload(
            async_client,
            auth_headers,
            [("ok.jpg", image_bytes(), "image/jpeg"), ("fake.png", content, "image/png")],
        )

        assert res.status_code == 415
        assert res.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
        assert res.json()["error"]["details"] == {"file_name": "fake.png"}
        # all or nothing: the valid file was not stored either
        assert storage.objects == {}

    @pytest.mark.asyncio
    async def test_file_too_large(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        storage: FakeStorage,
        monkeypatch: pytest.MonkeyPatch,
    ):
        large: bytes = image_bytes(size=(400, 400))
        monkeypatch.setattr(SETTINGS, "UPLOAD_MAX_FILE_BYTES", len(large) - 1)

        res: Response = await _upload(
            async_client, auth_headers, [("big.jpg", large, "image/jpeg")]
        )

        assert res.status_code == 413
        assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert res.json()["error"]["details"] == {"file_name": "big.jpg"}
        assert storage.objects == {}

    @pytest.mark.asyncio
    async def test_request_too_large_is_rejected_before_reading(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(uploads_router, "MAX_REQUEST_BYTES", 100)

        res: Response = await _upload(
            async_client, auth_headers, [("photo.jpg", image_bytes(), "image/jpeg")]
        )

        assert res.status_code == 413
        assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_too_many_files(self, async_client: AsyncClient, auth_headers: dict):
        files = [("p.jpg", image_bytes(), "image/jpeg")] * (SETTINGS.UPLOAD_MAX_FILES + 1)

        res: Response = await _upload(async_client, auth_headers, files)

        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    async def test_no_files(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.post("/uploads", headers=auth_headers)

        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_storage_failure_leaves_nothing_behind(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        storage.fail_uploads_after = 1

        res: Response = await _upload(
            async_client,
            auth_headers,
            [("a.jpg", image_bytes(), "image/jpeg"), ("b.jpg", image_bytes(), "image/jpeg")],
        )

        assert res.status_code == 502
        assert res.json()["error"]["code"] == "STORAGE_UPSTREAM_ERROR"
        # the first object was removed again
        assert storage.objects == {}

    @pytest.mark.asyncio
    async def test_not_authenticated(self, async_client: AsyncClient):
        res: Response = await _upload(async_client, {}, [("p.jpg", image_bytes(), "image/jpeg")])

        assert res.status_code == 401


class TestDeleteImage:
    @pytest.mark.asyncio
    async def test_delete(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        (file_id,) = await uploaded_ids(async_client, auth_headers)

        res: Response = await async_client.delete(f"/uploads/{file_id}", headers=auth_headers)

        assert res.status_code == 204
        assert storage.objects == {}
        res = await async_client.get(f"/uploads/{file_id}", headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_attached_photo(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        (file_id,) = await uploaded_ids(async_client, auth_headers)
        order = await async_client.post("/orders", json={"amount": 1000}, headers=auth_headers)
        await async_client.post(
            "/fulfillments",
            json={
                "order_id": order.json()["data"]["id"],
                "type": "delivery",
                "delivery_date": "2026-10-18T14:00:00Z",
                "file_ids": [file_id],
            },
            headers=auth_headers,
        )

        res: Response = await async_client.delete(f"/uploads/{file_id}", headers=auth_headers)

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "FILE_ALREADY_ATTACHED"
        assert len(storage.objects) == 1

    @pytest.mark.asyncio
    async def test_other_merchants_upload(
        self, async_client: AsyncClient, auth_headers: dict, storage: FakeStorage
    ):
        (file_id,) = await uploaded_ids(async_client, auth_headers)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.delete(f"/uploads/{file_id}", headers=other_headers)

        assert res.status_code == 404
        assert len(storage.objects) == 1


class TestGetImage:
    @pytest.mark.asyncio
    async def test_returns_the_image(self, async_client: AsyncClient, auth_headers: dict):
        (file_id,) = await uploaded_ids(async_client, auth_headers)

        res: Response = await async_client.get(f"/uploads/{file_id}", headers=auth_headers)

        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert res.headers["x-content-type-options"] == "nosniff"
        assert Image.open(BytesIO(res.content)).format == "JPEG"

    @pytest.mark.asyncio
    async def test_other_merchants_image(self, async_client: AsyncClient, auth_headers: dict):
        (file_id,) = await uploaded_ids(async_client, auth_headers)
        other_headers: dict = await sign_in_merchant(
            async_client, "other@example.com", "Other Store"
        )

        res: Response = await async_client.get(f"/uploads/{file_id}", headers=other_headers)

        assert res.status_code == 404
        assert res.json()["error"]["message"] == "File not found."
