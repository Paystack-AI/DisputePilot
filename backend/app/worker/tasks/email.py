from datetime import UTC, datetime

import resend
import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from resend.exceptions import ResendError

from app.api.models.enums import NotificationStatus
from app.api.models.notifications_log import NotificationLog
from app.core.config import get_settings
from app.database.session import sync_session
from app.worker.celery_app import celery_app
from app.worker.tasks.base import BaseTaskWithRetry

SETTINGS = get_settings()

resend.api_key = SETTINGS.RESEND_API_KEY


def _is_transient(exc: ResendError) -> bool:
    """Rate limits and server side errors can succeed on a retry. resend also
    reports network failures as code 500. Anything else (bad payload, bad key)
    fails the same way every time"""
    try:
        code = int(exc.code)
    except (TypeError, ValueError):
        return False
    return code == 429 or code >= 500


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def send_email(
    self,
    email_id: str,
    recipient_email: str,
    subject: str,
    html: str,
    notification_id: str | None = None,
):
    """Send any email: the caller builds the subject and body, so one task serves
    every kind of email. The task id is passed to resend as the idempotency key; it
    stays the same across retries and redeliveries, so the same email is never
    sent twice. notification_id is the notifications_log row to mark sent or failed"""
    try:
        resend.Emails.send(
            {
                "from": SETTINGS.API_EMAIL,
                "to": recipient_email,
                "subject": subject,
                "html": html,
            },
            options={"idempotency_key": self.request.id},
        )
    except ResendError as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Error occured while sending email {email_id}: {code} {error_type}",
            email_id=email_id,
            code=str(exc.code),
            error_type=exc.error_type,
        )

        transient: bool = _is_transient(exc)
        if not transient or self.request.retries >= self.max_retries:
            _mark_notification(notification_id, NotificationStatus.FAILED, {"error": str(exc.code)})
        if transient:
            self.retry_or_reject(exc)
        raise Reject(exc, requeue=False) from exc

    _mark_notification(notification_id, NotificationStatus.SENT)
    sentry_logger.info("Email {email_id} sent", email_id=email_id)


def _mark_notification(
    notification_id: str | None, status: NotificationStatus, details: dict | None = None
):
    """Record the outcome on the notification; never fails the email itself"""
    if not notification_id:
        return
    try:
        with sync_session() as session:
            notification: NotificationLog | None = session.get(NotificationLog, notification_id)
            if not notification:
                return
            notification.status = status
            if status == NotificationStatus.SENT:
                notification.sent_at = datetime.now(UTC)
            if details:
                notification.metadata_ = {**(notification.metadata_ or {}), **details}
            session.commit()
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Notification {notification_id} could not be updated", notification_id=notification_id
        )
