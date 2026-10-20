from uuid import uuid4

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ServerError
from app.worker.tasks.email import send_email

# rabbitmq delivers higher priorities first (the queue allows 0-10). auth emails
# have someone waiting on them, so they go ahead of background work
AUTH_EMAIL_PRIORITY: int = 8


class EmailService:
    async def send(
        self,
        recipient_email: str,
        subject: str,
        html: str,
        priority: int = AUTH_EMAIL_PRIORITY,
        notification_id: str | None = None,
    ) -> str:
        """Queue an email for the worker to send; returns its id, which the worker
        also uses as the idempotency key with resend"""
        email_id: str = str(uuid4())

        try:
            # publishing talks to the broker over a blocking connection
            await run_in_threadpool(
                send_email.apply_async,
                kwargs={
                    "email_id": email_id,
                    "recipient_email": recipient_email,
                    "subject": subject,
                    "html": html,
                    "notification_id": notification_id,
                },
                priority=priority,
            )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            sentry_logger.error("Error occured while queueing email {email_id}", email_id=email_id)
            raise ServerError() from exc

        return email_id
