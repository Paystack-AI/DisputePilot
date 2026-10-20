"""Merchant emails sent from celery tasks, recorded in notifications_log (the api's
NotificationService does the same for requests)."""

from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.orm import Session

from app.api.models.enums import NotificationChannel, NotificationMessageType, NotificationStatus
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.repo.disputes import SyncDisputeRepository
from app.worker.tasks.email import send_email

# dispute alerts have a deadline: right behind auth emails (8)
DISPUTE_EMAIL_PRIORITY: int = 7


def email_merchant(
    session: Session,
    merchant: Merchant,
    message_type: NotificationMessageType,
    subject: str,
    html: str,
    dispute_id: UUID | None = None,
    metadata: dict | None = None,
    attachment_object: str | None = None,
    attachment_name: str | None = None,
) -> UUID | None:
    """Records and queues the email when the merchant has email notifications on. Commits;
    never raises, the event that caused it is already saved"""
    recipient: str | None = merchant.email or merchant.google_email
    repo = SyncDisputeRepository(session)
    settings = repo.settings(merchant.id)
    if not recipient or (settings and not settings.notification_email):
        return None

    try:
        notification: NotificationLog = repo.add_notification(
            NotificationLog(
                merchant_id=merchant.id,
                dispute_id=dispute_id,
                channel=NotificationChannel.EMAIL,
                message_type=message_type,
                status=NotificationStatus.PENDING,
                metadata_=metadata or {},
            )
        )
        session.commit()
        send_email.apply_async(
            kwargs={
                "email_id": str(notification.id),
                "recipient_email": recipient,
                "subject": subject,
                "html": html,
                "notification_id": str(notification.id),
                "attachment_object": attachment_object,
                "attachment_name": attachment_name,
            },
            priority=DISPUTE_EMAIL_PRIORITY,
        )
    except Exception as exc:
        session.rollback()
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "{message_type} email could not be queued for merchant {merchant_id}",
            message_type=message_type.value,
            merchant_id=str(merchant.id),
        )
        return None

    return notification.id
