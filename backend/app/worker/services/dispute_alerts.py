"""What the merchant hears about a dispute, the same whichever way paystack told us (the
webhook or the poller): live updates on the dashboard and, for the important moments, an
email. Called after the intake is committed."""

from datetime import UTC, datetime

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.enums import NotificationMessageType
from app.api.models.merchants import Merchant
from app.api.services.email_templates import (
    deadline_warning_email,
    dispute_alert_email,
    dispute_resolved_email,
)
from app.api.services.events import publish_event_sync
from app.database.session import sync_redis_client
from app.worker.services.disputes import DisputeIntake
from app.worker.services.notifications import email_merchant


def publish(merchant_id: str, event_type: str, data: dict):
    """Live update for the merchant's dashboards; best effort"""
    try:
        publish_event_sync(sync_redis_client, merchant_id, event_type, data)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "{event_type} could not be published for merchant {merchant_id}",
            event_type=event_type,
            merchant_id=merchant_id,
        )


def hours_left(dispute: Dispute, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    return max(round((dispute.due_at - now).total_seconds() / 3600), 0)


def announce_created(session: Session, merchant: Merchant, intake: DisputeIntake):
    dispute: Dispute = intake.dispute
    publish(
        str(merchant.id),
        "dispute.created",
        {
            "dispute_id": str(dispute.id),
            "amount": dispute.amount,
            "currency": dispute.currency.value,
            "due_at": dispute.due_at.isoformat(),
        },
    )
    subject, html = dispute_alert_email(
        merchant.business_name,
        dispute.amount,
        dispute.currency.value,
        intake.reference,
        dispute.due_at,
    )
    email_merchant(
        session, merchant, NotificationMessageType.DISPUTE_ALERT, subject, html, dispute.id
    )


def announce_deadline(
    session: Session, merchant: Merchant, dispute: Dispute, reference: str, hours: int
):
    publish(
        str(merchant.id),
        "deadline.warning",
        {"dispute_id": str(dispute.id), "hours_remaining": hours},
    )
    subject, html = deadline_warning_email(reference, dispute.due_at)
    email_merchant(
        session,
        merchant,
        NotificationMessageType.DEADLINE_WARNING,
        subject,
        html,
        dispute.id,
        {"hours_remaining": hours},
    )


def announce_update(session: Session, merchant: Merchant, intake: DisputeIntake):
    """A known dispute moved; resolved ones also get an email"""
    dispute: Dispute = intake.dispute
    publish(
        str(merchant.id),
        "dispute.updated",
        {
            "dispute_id": str(dispute.id),
            "status": dispute.status.value,
            "paystack_status": dispute.paystack_status,
        },
    )
    if intake.resolved_now:
        subject, html = dispute_resolved_email(intake.reference, dispute.status.value)
        email_merchant(
            session, merchant, NotificationMessageType.DISPUTE_RESOLVED, subject, html, dispute.id
        )


def announce(session: Session, merchant: Merchant, intake: DisputeIntake):
    """New disputes are alerted, changed ones updated; an unchanged one says nothing"""
    if intake.created:
        announce_created(session, merchant, intake)
    elif intake.changed:
        announce_update(session, merchant, intake)
