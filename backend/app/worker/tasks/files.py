from datetime import UTC, datetime, timedelta

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from minio.error import S3Error
from sqlalchemy import select

from app.api.clients.minio import MinioStorage, create_minio_storage
from app.api.models.files import StoredFile
from app.core.config import get_settings
from app.database.session import sync_session
from app.worker.celery_app import celery_app

SETTINGS = get_settings()

# per run, so one run never holds a long transaction; the rest go on the next run
CLEANUP_BATCH: int = 500

# one storage client per worker process
_storage: MinioStorage | None = None


def _get_storage() -> MinioStorage:
    global _storage
    if _storage is None:
        _storage = create_minio_storage()
    return _storage


@celery_app.task
def delete_unattached_files() -> int:
    """Deletes uploads never attached to a fulfillment or dispute (or detached from one)
    after UPLOAD_UNATTACHED_TTL_HOURS; returns how many were removed"""
    cutoff: datetime = datetime.now(UTC) - timedelta(hours=SETTINGS.UPLOAD_UNATTACHED_TTL_HOURS)
    client = _get_storage().client
    removed: int = 0

    with sync_session() as session:
        files: list[StoredFile] = list(
            session.scalars(
                select(StoredFile)
                .where(
                    StoredFile.fulfillment_id.is_(None),
                    StoredFile.dispute_id.is_(None),
                    StoredFile.created_at < cutoff,
                )
                .order_by(StoredFile.created_at)
                .limit(CLEANUP_BATCH)
                # a request attaching one of these files waits, then sees it gone
                .with_for_update(skip_locked=True)
            )
        )

        for stored_file in files:
            try:
                client.remove_object(SETTINGS.MINIO_BUCKET, stored_file.object_name)
            except S3Error as exc:
                # already gone from storage: the row can still go
                if exc.code not in ("NoSuchKey", "NoSuchObject"):
                    sentry_sdk.capture_exception(exc)
                    continue
            except Exception as exc:
                # storage unreachable: keep the row, the next run retries it
                sentry_sdk.capture_exception(exc)
                continue

            session.delete(stored_file)
            removed += 1

        session.commit()

    sentry_logger.info("Deleted {count} unattached uploads", count=str(removed))
    return removed
