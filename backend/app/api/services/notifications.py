"""Merchant notifications by email, recorded in notifications_log. In-app notifications go
out as live events (services.events); this covers what the merchant also gets by email.
"""

from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.enums import NotificationChannel, NotificationMessageType, NotificationStatus
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.models.reconciliation_sessions import ReconciliationSession
from app.api.repo.notifications import NotificationLogRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.services.email import EmailService
from app.api.services.email_templates import reconciliation_summary_email
from app.core.exceptions import ServerError

# below auth emails (8) and syncs: nobody is waiting on a summary
SUMMARY_EMAIL_PRIORITY: int = 3


class NotificationService:
    def __init__(self, email_service: EmailService | None = None):
        self._email_service = email_service or EmailService()

    async def reconciliation_summary(
        self,
        merchant: Merchant,
        settings: MerchantSettings | None,
        session: ReconciliationSession,
        totals: dict[str, int],
        uow: UnitOfWorkRepository,
    ) -> UUID | None:
        """Email the completed session's counts when the merchant has email notifications
        on. Never raises: the session is already complete"""
        recipient: str | None = merchant.email or merchant.google_email
        if not recipient or (settings and not settings.notification_email):
            return None

        notification = NotificationLog(
            merchant_id=merchant.id,
            channel=NotificationChannel.EMAIL,
            message_type=NotificationMessageType.RECONCILIATION_SUMMARY,
            status=NotificationStatus.PENDING,
            metadata_={"session_id": str(session.id), "totals": totals},
        )
        try:
            uow.repo(NotificationLogRepository).add(model=notification)
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            sentry_sdk.capture_exception(exc)
            sentry_logger.error(
                "Reconciliation summary for merchant {merchant_id} could not be recorded",
                merchant_id=str(merchant.id),
            )
            return None

        subject, html = reconciliation_summary_email(
            merchant.business_name, session.date_range_start, session.date_range_end, totals
        )
        try:
            email_id: str = await self._email_service.send(
                recipient,
                subject,
                html,
                priority=SUMMARY_EMAIL_PRIORITY,
                notification_id=str(notification.id),
            )
        except ServerError:
            notification.status = NotificationStatus.FAILED
            notification.metadata_ = {**notification.metadata_, "error": "not_queued"}
            await uow.commit()
            return notification.id

        notification.metadata_ = {**notification.metadata_, "email_id": email_id}
        await uow.commit()
        return notification.id
