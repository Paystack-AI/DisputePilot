"""The merchant's response to paystack, run in the background (spec 3.2.1).

Submit (declined, with evidence):
  chargeback flow: pdf -> upload url -> PUT pdf -> resolve
  fraud flow:      pdf -> POST evidence (customer identity) -> upload url -> PUT pdf
                   -> resolve with the evidence id
Accept (merchant-accepted): a short acceptance letter -> upload -> resolve

Each step's result (the pdf, the evidence id, paystack's file name) is saved as it
completes, so a retry carries on from where the last attempt stopped.
"""

from datetime import UTC, datetime
from uuid import UUID

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.clients.minio import MinioStorage, create_minio_storage
from app.api.clients.paystack import PaystackClient, PaystackError
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    DisputeStatus,
    NotificationMessageType,
    SubmissionFlow,
    SubmissionState,
)
from app.api.models.merchants import Merchant
from app.api.repo.disputes import SyncDisputeRepository
from app.api.services.email_templates import dispute_submitted_email
from app.api.services.evidence_templates import acceptance_message
from app.core.config import get_settings
from app.core.security import Security
from app.database.session import sync_session
from app.worker.celery_app import celery_app
from app.worker.services.dispute_alerts import publish
from app.worker.services.evidence_pdf import acceptance_html, evidence_html, render_pdf
from app.worker.services.notifications import email_merchant
from app.worker.tasks.base import BaseTaskWithRetry
from app.worker.tasks.transaction_sync import _http_client

SETTINGS = get_settings()
SECURITY = Security()

DECLINED: str = "declined"
MERCHANT_ACCEPTED: str = "merchant-accepted"
PDF: str = "application/pdf"
# paystack's resolve message is free text; kept short
MESSAGE_LIMIT: int = 500

_storage: MinioStorage | None = None


def _get_storage() -> MinioStorage:
    global _storage
    if _storage is None:
        _storage = create_minio_storage()
    return _storage


def _is_retryable(exc: Exception) -> bool:
    return (isinstance(exc, PaystackError) and exc.retryable) or isinstance(exc, OperationalError)


def _client(merchant: Merchant) -> PaystackClient:
    return PaystackClient(
        SECURITY.decrypt_secret_key_sync(merchant.paystack_secret_key), _http_client()
    )


class _Run:
    """One attempt at a response, holding the dispute's row lock between steps"""

    def __init__(self, session: Session, dispute_id: UUID):
        self.session = session
        self.repo = SyncDisputeRepository(session)
        self.dispute_id = dispute_id
        self.dispute: Dispute | None = self.repo.get_by_id_for_update(dispute_id)

    def save(self):
        """Commit the finished step and lock the row again for the next"""
        self.session.commit()
        self.dispute = self.repo.get_by_id_for_update(self.dispute_id)


def _upload_to_paystack(run: _Run, client: PaystackClient, pdf: bytes, name: str):
    dispute = run.dispute
    if dispute.paystack_uploaded_filename:
        return
    upload: dict = client.get_dispute_upload_url(dispute.paystack_dispute_id, upload_filename=name)[
        "data"
    ]
    client.upload_to_signed_url(upload["signedUrl"], pdf, PDF)
    dispute.paystack_uploaded_filename = upload["fileName"]
    run.save()


def _fail(dispute_id: str, exc: Exception):
    """Out of retries, or a failure retrying can't fix: the merchant sees why and can try
    again (the steps already done are kept)"""
    with sync_session() as session:
        repo = SyncDisputeRepository(session)
        dispute: Dispute | None = repo.get_by_id_for_update(UUID(dispute_id))
        if not dispute:
            return
        dispute.submission_state = SubmissionState.FAILED
        dispute.submission_error = (
            str(exc)[:1000] if isinstance(exc, PaystackError) else "The response could not be sent."
        )
        session.commit()
        publish(
            str(dispute.merchant_id),
            "dispute.updated",
            {
                "dispute_id": dispute_id,
                "status": dispute.status.value,
                "submission_state": dispute.submission_state.value,
                "submission_error": dispute.submission_error,
            },
        )


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def submit_dispute(self, dispute_id: str):
    """Declines the dispute with the approved evidence"""
    try:
        with sync_session() as session:
            run = _Run(session, UUID(dispute_id))
            dispute = run.dispute
            if not dispute or dispute.submission_state != SubmissionState.SUBMITTING:
                return

            merchant: Merchant = run.repo.merchant(dispute.merchant_id)
            snapshot: dict | None = run.repo.submitted_snapshot(dispute.id)
            if not snapshot:
                raise ValueError("no approved evidence to submit")
            storage: MinioStorage = _get_storage()
            client: PaystackClient = _client(merchant)

            # 1. the pdf, from exactly what the merchant approved
            if dispute.evidence_pdf_object:
                pdf: bytes = storage.retrieve_sync(
                    SETTINGS.MINIO_BUCKET, dispute.evidence_pdf_object
                )
            else:
                html: str = evidence_html(
                    snapshot, lambda name: storage.retrieve_sync(SETTINGS.MINIO_BUCKET, name)
                )
                pdf = render_pdf(html)
                object_name: str = (
                    f"disputes/{merchant.id}/{dispute.id}/evidence-v{dispute.evidence_version}.pdf"
                )
                storage.upload_bytes_sync(SETTINGS.MINIO_BUCKET, object_name, pdf, PDF)
                dispute.evidence_pdf_object = object_name
                run.save()
                dispute = run.dispute

            # 2. fraud claims: the customer's identity, which resolve references
            fraud: bool = snapshot.get("submission_flow") == SubmissionFlow.FRAUD_FLOW.value
            if fraud and not dispute.paystack_evidence_id:
                evidence: dict = client.add_dispute_evidence(
                    dispute.paystack_dispute_id, **snapshot["fraud_evidence"]
                )["data"]
                dispute.paystack_evidence_id = int(evidence["id"])
                run.save()
                dispute = run.dispute

            # 3. the pdf to paystack's storage
            _upload_to_paystack(
                run, client, pdf, f"dispute-{dispute.paystack_dispute_id}-evidence.pdf"
            )
            dispute = run.dispute

            # 4. decline, with the uploaded file (and the evidence id for fraud)
            conclusion: str = snapshot["document"].get("conclusion") or ""
            client.resolve_dispute(
                dispute.paystack_dispute_id,
                resolution=DECLINED,
                message=(conclusion or "The merchant declines this dispute.")[:MESSAGE_LIMIT],
                # declining refunds nothing; paystack still requires the field
                refund_amount=0,
                uploaded_filename=dispute.paystack_uploaded_filename,
                evidence=dispute.paystack_evidence_id if fraud else None,
            )

            now: datetime = datetime.now(UTC)
            dispute.status = DisputeStatus.SUBMITTED
            dispute.submission_state = SubmissionState.SUBMITTED
            dispute.submission_error = None
            dispute.submitted_at = now
            session.commit()

            publish(
                str(merchant.id),
                "dispute.updated",
                {
                    "dispute_id": dispute_id,
                    "status": dispute.status.value,
                    "submission_state": dispute.submission_state.value,
                },
            )
            subject, body = dispute_submitted_email(dispute.paystack_reference, dispute.due_at)
            email_merchant(
                session,
                merchant,
                NotificationMessageType.DISPUTE_SUBMITTED,
                subject,
                body,
                dispute.id,
                attachment_object=dispute.evidence_pdf_object,
                attachment_name=f"dispute-{dispute.paystack_dispute_id}-evidence.pdf",
            )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Submitting dispute {dispute_id} failed: {error}",
            dispute_id=dispute_id,
            error=exc.__class__.__name__,
        )
        if _is_retryable(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc
        _fail(dispute_id, exc)
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info("Dispute {dispute_id} submitted to paystack", dispute_id=dispute_id)


@celery_app.task(base=BaseTaskWithRetry, bind=True)
def accept_dispute(self, dispute_id: str, message: str | None = None):
    """Concedes the dispute: paystack refunds the customer"""
    try:
        with sync_session() as session:
            run = _Run(session, UUID(dispute_id))
            dispute = run.dispute
            if not dispute or dispute.submission_state != SubmissionState.ACCEPTING:
                return

            merchant: Merchant = run.repo.merchant(dispute.merchant_id)
            reference: str = run.repo.transaction_reference(dispute.transaction_id)
            client: PaystackClient = _client(merchant)
            text: str = acceptance_message(message)

            # paystack's resolve needs an uploaded file, so a one page acceptance letter
            pdf: bytes = render_pdf(
                acceptance_html(
                    merchant.business_name,
                    str(dispute.paystack_dispute_id),
                    reference,
                    dispute.amount,
                    dispute.currency.value,
                    text,
                    datetime.now(UTC),
                )
            )
            _upload_to_paystack(
                run, client, pdf, f"dispute-{dispute.paystack_dispute_id}-acceptance.pdf"
            )
            dispute = run.dispute

            client.resolve_dispute(
                dispute.paystack_dispute_id,
                resolution=MERCHANT_ACCEPTED,
                message=text[:MESSAGE_LIMIT],
                refund_amount=dispute.amount,
                uploaded_filename=dispute.paystack_uploaded_filename,
            )

            # the resolution itself arrives from paystack (webhook or poll) as lost
            dispute.submission_state = SubmissionState.ACCEPTED
            dispute.submission_error = None
            dispute.submitted_at = datetime.now(UTC)
            session.commit()
            publish(
                str(merchant.id),
                "dispute.updated",
                {
                    "dispute_id": dispute_id,
                    "status": dispute.status.value,
                    "submission_state": dispute.submission_state.value,
                },
            )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        sentry_logger.error(
            "Accepting dispute {dispute_id} failed: {error}",
            dispute_id=dispute_id,
            error=exc.__class__.__name__,
        )
        if _is_retryable(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=self._backoff_countdown()) from exc
        _fail(dispute_id, exc)
        raise Reject(exc, requeue=False) from exc

    sentry_logger.info("Dispute {dispute_id} accepted on paystack", dispute_id=dispute_id)
