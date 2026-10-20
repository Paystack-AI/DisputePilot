from io import BytesIO

import certifi
import sentry_sdk
import sentry_sdk.logger as sentry_logger
import urllib3
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, StorageUpstreamError

SETTINGS = get_settings()

DEFAULT_CONTENT_TYPE: str = "application/octet-stream"
# multipart chunk size for uploads of unknown length (minio's minimum is 5 MiB)
PART_SIZE: int = 10 * 1024 * 1024


def _http_pool() -> urllib3.PoolManager:
    """The sdk's default pool retries a refused connection with growing backoff (~30 s in
    total) before failing. Storage being down should fail fast instead: a short connect
    timeout and two retries for transient server errors. Reads keep a long timeout for
    large files"""
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3, read=120),
        # connect=0: a refused or unreachable server is not retried (it will not be up a
        # moment later); 5xx responses are
        retries=urllib3.Retry(
            total=2, connect=0, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]
        ),
        maxsize=10,
        cert_reqs="CERT_REQUIRED",
        ca_certs=certifi.where(),
    )


class MinioStorage:
    """Object storage for evidence files and generated PDFs. The minio sdk is blocking, so
    every public method runs its call in the threadpool"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        region: str | None = None,
    ):
        self.endpoint = endpoint
        # a fixed region avoids a region lookup request before each call
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
            http_client=_http_pool(),
        )

    def _upload(
        self,
        bucket_name: str,
        object_name: str,
        data,
        length: int,
        content_type: str,
    ):
        self.client.put_object(
            bucket_name,
            object_name,
            data,
            length,
            content_type=content_type,
            # only used when the length is unknown (-1)
            part_size=PART_SIZE if length == -1 else 0,
        )

    def _retrieve(self, bucket_name: str, object_name: str) -> bytes:
        response = self.client.get_object(bucket_name, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _ensure_bucket(self, bucket_name: str):
        if self.client.bucket_exists(bucket_name):
            return
        try:
            self.client.make_bucket(bucket_name)
        except S3Error as exc:
            # created by another worker between the check and the create
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    async def _run(self, func, *args):
        """Runs a blocking sdk call in the threadpool and maps its failures to app errors"""
        try:
            return await run_in_threadpool(func, *args)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise NotFoundError("File") from exc
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Object storage error: {code}", code=str(exc.code))
            raise StorageUpstreamError() from exc
        except (urllib3.exceptions.HTTPError, OSError) as exc:
            # unreachable server, timeouts, refused connections (after the sdk's retries)
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Object storage unreachable at {endpoint}", endpoint=self.endpoint)
            raise StorageUpstreamError() from exc

    async def upload(self, bucket_name: str, object_name: str, file: UploadFile):
        """Streams the upload in chunks instead of reading it all into memory. The sdk reads
        file.file on the worker thread, like UploadFile.read() would, so the loop is free"""
        await file.seek(0)
        await self._run(
            self._upload,
            bucket_name,
            object_name,
            file.file,
            file.size if file.size is not None else -1,
            file.content_type or DEFAULT_CONTENT_TYPE,
        )

    async def upload_bytes(
        self,
        bucket_name: str,
        object_name: str,
        data: bytes,
        content_type: str = DEFAULT_CONTENT_TYPE,
    ):
        """For content the backend generates, e.g. evidence PDFs"""
        await self._run(
            self._upload, bucket_name, object_name, BytesIO(data), len(data), content_type
        )

    async def retrieve(self, bucket_name: str, object_name: str) -> bytes:
        """Raises NotFoundError when the object does not exist"""
        return await self._run(self._retrieve, bucket_name, object_name)

    async def delete(self, bucket_name: str, object_name: str):
        await self._run(self.client.remove_object, bucket_name, object_name)

    # blocking versions for celery tasks, which run without an event loop

    def upload_bytes_sync(
        self,
        bucket_name: str,
        object_name: str,
        data: bytes,
        content_type: str = DEFAULT_CONTENT_TYPE,
    ):
        self._upload(bucket_name, object_name, BytesIO(data), len(data), content_type)

    def retrieve_sync(self, bucket_name: str, object_name: str) -> bytes:
        return self._retrieve(bucket_name, object_name)

    async def ensure_bucket(self, bucket_name: str):
        """Creates the bucket when missing; uploads also do this on first use"""
        await self._run(self._ensure_bucket, bucket_name)


def create_minio_storage() -> MinioStorage:
    return MinioStorage(
        endpoint=SETTINGS.MINIO_ENDPOINT,
        access_key=SETTINGS.MINIO_ACCESS_KEY,
        secret_key=SETTINGS.MINIO_SECRET_KEY,
        secure=SETTINGS.MINIO_SECURE,
        region=SETTINGS.MINIO_REGION,
    )
