import resend
import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from resend.exceptions import ResendError

from app.core.config import get_settings
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
def send_email(self, email_id: str, recipient_email: str, subject: str, html: str):
    """Send any email: the caller builds the subject and body, so one task serves
    every kind of email. The task id is passed to resend as the idempotency key; it
    stays the same across retries and redeliveries, so the same email is never
    sent twice"""
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

        if _is_transient(exc):
            self.retry_or_reject(exc)
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info("Email {email_id} sent", email_id=email_id)
