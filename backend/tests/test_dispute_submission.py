from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock, call, patch

import pytest
from celery.exceptions import Reject
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.clients.paystack import PaystackRequestError
from app.api.models.disputes import Dispute
from app.api.models.enums import (
    Currency,
    DisputeStatus,
    EvidenceChange,
    NotificationMessageType,
    SubmissionState,
    TransactionChannel,
    TransactionStatus,
)
from app.api.models.evidence_revisions import EvidenceRevision
from app.api.models.merchants import Merchant
from app.api.models.notifications_log import NotificationLog
from app.api.models.transactions import Transaction
from app.worker.services.evidence_pdf import evidence_html, prepare_image
from app.worker.tasks.dispute_submission import accept_dispute, submit_dispute
from tests.test_transaction_sync import _merchant

PDF: bytes = b"%PDF-1.7 fake"

DOCUMENT: dict = {
    "version": 3,
    "generation_source": "ai",
    "generated_at": None,
    "edited_at": None,
    "header": {
        "business_name": 'Acme "Shoes" & Co',
        "paystack_integration_id": "100200",
        "document_date": "2026-10-21T10:00:00+00:00",
        "dispute_reference": "358950",
        "transaction_reference": "v3mjfgbnc19v97x",
    },
    "transaction_receipt": {
        "paid_at": "2026-10-10T12:00:00+00:00",
        "amount": 5800,
        "currency": "NGN",
        "channel": "card",
        "reference": "v3mjfgbnc19v97x",
        "customer_email": "john@example.com",
        "customer_name": "John Doe",
    },
    "order_details": {
        "order_number": "A-1",
        "description": "Blue sneakers",
        "created_at": "2026-10-09T12:00:00+00:00",
        "amount": 5800,
        "currency": "NGN",
    },
    "fulfillment_evidence": [
        {
            "type": "delivery",
            "delivery_date": "2026-10-11T09:00:00+00:00",
            "tracking_number": "GIG-0012",
            "recipient_name": "John Doe",
            "delivery_address": "3a Ladoke Street",
            "notes": None,
            "photos": [
                {
                    "file_id": "11111111-1111-1111-1111-111111111111",
                    "file_name": "door.jpg",
                    "caption": "Parcel at the door",
                    "source": "fulfillment",
                }
            ],
        }
    ],
    "narrative": "On 10 October John Doe paid.\n\nThe parcel was delivered on 11 October.",
    "supporting_documents": [],
    "customer_history": {"payment_count": 4, "first_payment_at": None, "prior_disputes": 0},
    "conclusion": "Please resolve this dispute in the merchant's favour.",
    "missing_evidence": [],
    "quality": None,
    "editable": ["narrative", "supporting_documents", "conclusion"],
}
FILES: dict = {"11111111-1111-1111-1111-111111111111": "merchant/door.jpg"}
FRAUD_EVIDENCE: dict = {
    "customer_email": "john@example.com",
    "customer_name": "John Doe",
    "customer_phone": "08000000000",
    "service_details": "Blue sneakers",
    "delivery_address": "3a Ladoke Street",
    "delivery_date": "2026-10-11",
}


def _jpeg(width: int = 1600, height: int = 900) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), "red").save(out, format="JPEG")
    return out.getvalue()


def _setup(
    sync_db: Session, flow: str = "chargeback_flow", state=SubmissionState.SUBMITTING
) -> tuple[Merchant, Dispute]:
    merchant: Merchant = _merchant(sync_db, paystack_secret_key="encrypted")
    transaction = Transaction(
        merchant_id=merchant.id,
        paystack_transaction_id=896467688,
        paystack_reference="v3mjfgbnc19v97x",
        amount=5800,
        currency=Currency.NGN,
        channel=TransactionChannel.CARD,
        status=TransactionStatus.SUCCESS,
        paystack_created_at=datetime.now(UTC),
        paid_at=datetime.now(UTC),
    )
    sync_db.add(transaction)
    sync_db.flush()
    dispute = Dispute(
        merchant_id=merchant.id,
        transaction_id=transaction.id,
        paystack_dispute_id=358950,
        paystack_reference="v3mjfgbnc19v97x",
        amount=5800,
        due_at=datetime.now(UTC) + timedelta(hours=10),
        status=DisputeStatus.EVIDENCE_GENERATED,
        submission_state=state,
        evidence_version=3,
    )
    sync_db.add(dispute)
    sync_db.flush()
    sync_db.add(
        EvidenceRevision(
            dispute_id=dispute.id,
            merchant_id=merchant.id,
            version=3,
            change=EvidenceChange.SUBMITTED,
            snapshot={
                "document": DOCUMENT,
                "files": FILES,
                "submission_flow": flow,
                "fraud_evidence": FRAUD_EVIDENCE if flow == "fraud_flow" else None,
            },
        )
    )
    sync_db.commit()
    return merchant, dispute


@pytest.fixture
def worker(sync_db: Session):
    """The submission task on the test database with paystack, storage and the pdf
    printer faked"""
    client = MagicMock()
    client.get_dispute_upload_url.return_value = {
        "data": {"signedUrl": "https://upload.example/abc", "fileName": "qesp8a4df1"}
    }
    client.add_dispute_evidence.return_value = {"data": {"id": 4321}}
    storage = MagicMock()
    storage.retrieve_sync.return_value = _jpeg()
    with (
        patch("app.worker.tasks.dispute_submission.sync_session", lambda: nullcontext(sync_db)),
        patch("app.worker.tasks.dispute_submission._client", return_value=client),
        patch("app.worker.tasks.dispute_submission._get_storage", return_value=storage),
        patch("app.worker.tasks.dispute_submission.render_pdf", return_value=PDF) as render,
        patch("app.worker.tasks.dispute_submission.publish") as publish,
        patch("app.worker.services.notifications.send_email.apply_async") as email,
    ):
        yield {
            "db": sync_db,
            "client": client,
            "storage": storage,
            "render": render,
            "publish": publish,
            "email": email,
        }


class TestSubmit:
    @pytest.mark.asyncio
    async def test_chargeback_flow(self, worker: dict):
        db: Session = worker["db"]
        merchant, dispute = _setup(db)

        submit_dispute(str(dispute.id))

        client: MagicMock = worker["client"]
        client.add_dispute_evidence.assert_not_called()
        client.get_dispute_upload_url.assert_called_once_with(
            358950, upload_filename="dispute-358950-evidence.pdf"
        )
        client.upload_to_signed_url.assert_called_once_with(
            "https://upload.example/abc", PDF, "application/pdf"
        )
        client.resolve_dispute.assert_called_once_with(
            358950,
            resolution="declined",
            message="Please resolve this dispute in the merchant's favour.",
            refund_amount=0,
            uploaded_filename="qesp8a4df1",
            evidence=None,
        )
        worker["storage"].upload_bytes_sync.assert_called_once()

        db.refresh(dispute)
        assert dispute.status == DisputeStatus.SUBMITTED
        assert dispute.submission_state == SubmissionState.SUBMITTED
        assert dispute.submitted_at is not None
        assert dispute.evidence_pdf_object == (
            f"disputes/{merchant.id}/{dispute.id}/evidence-v3.pdf"
        )

        # the pdf rendered from the approved snapshot, the fulfillment photo embedded
        html: str = worker["render"].call_args.args[0]
        assert "Blue sneakers" in html and "data:image/jpeg;base64," in html

        email_kwargs: dict = worker["email"].call_args.kwargs["kwargs"]
        assert email_kwargs["attachment_object"] == dispute.evidence_pdf_object
        assert email_kwargs["attachment_name"] == "dispute-358950-evidence.pdf"
        assert db.scalar(select(NotificationLog.message_type)) == (
            NotificationMessageType.DISPUTE_SUBMITTED
        )
        assert worker["publish"].call_args.args[1] == "dispute.updated"

    @pytest.mark.asyncio
    async def test_fraud_flow_sends_identity_evidence(self, worker: dict):
        db: Session = worker["db"]
        _, dispute = _setup(db, flow="fraud_flow")

        submit_dispute(str(dispute.id))

        client: MagicMock = worker["client"]
        client.add_dispute_evidence.assert_called_once_with(358950, **FRAUD_EVIDENCE)
        assert client.resolve_dispute.call_args.kwargs["evidence"] == 4321
        db.refresh(dispute)
        assert dispute.paystack_evidence_id == 4321

    @pytest.mark.asyncio
    async def test_retry_resumes_after_the_upload(self, worker: dict):
        db: Session = worker["db"]
        _, dispute = _setup(db)
        client: MagicMock = worker["client"]
        client.resolve_dispute.side_effect = [PaystackRequestError("bad request", 400), None]

        with pytest.raises(Reject):
            submit_dispute(str(dispute.id))

        db.refresh(dispute)
        assert dispute.submission_state == SubmissionState.FAILED
        assert dispute.submission_error
        # what finished is kept: the pdf and paystack's copy of it
        assert dispute.evidence_pdf_object and dispute.paystack_uploaded_filename == "qesp8a4df1"

        # the merchant tries again (the api sets submitting again)
        dispute.submission_state = SubmissionState.SUBMITTING
        db.commit()
        submit_dispute(str(dispute.id))

        assert worker["render"].call_count == 1
        assert client.get_dispute_upload_url.call_count == 1
        assert client.resolve_dispute.call_count == 2
        db.refresh(dispute)
        assert dispute.submission_state == SubmissionState.SUBMITTED

    @pytest.mark.asyncio
    async def test_nothing_to_do_unless_submitting(self, worker: dict):
        _, dispute = _setup(worker["db"], state=SubmissionState.SUBMITTED)
        submit_dispute(str(dispute.id))
        worker["client"].resolve_dispute.assert_not_called()


class TestAccept:
    @pytest.mark.asyncio
    async def test_accept_with_a_letter(self, worker: dict):
        db: Session = worker["db"]
        _, dispute = _setup(db, state=SubmissionState.ACCEPTING)

        accept_dispute(str(dispute.id), "We refunded the duplicate charge.")

        client: MagicMock = worker["client"]
        assert client.get_dispute_upload_url.call_args == call(
            358950, upload_filename="dispute-358950-acceptance.pdf"
        )
        client.resolve_dispute.assert_called_once_with(
            358950,
            resolution="merchant-accepted",
            message="We refunded the duplicate charge.",
            refund_amount=5800,
            uploaded_filename="qesp8a4df1",
        )
        assert "We refunded the duplicate charge." in worker["render"].call_args.args[0]
        db.refresh(dispute)
        assert dispute.submission_state == SubmissionState.ACCEPTED
        # lost is set when paystack confirms the resolution
        assert dispute.status == DisputeStatus.EVIDENCE_GENERATED


class TestEvidenceHtml:
    def test_sections_in_order_and_escaped(self):
        html: str = evidence_html({"document": DOCUMENT, "files": FILES}, lambda name: _jpeg())

        order: list[int] = [
            html.index(heading)
            for heading in (
                "Transaction receipt",
                "Order details",
                "Fulfillment evidence",
                "Statement",
                "Supporting documents",
                "Customer history",
                "Conclusion",
            )
        ]
        assert order == sorted(order)
        assert "Exhibit 1: Parcel at the door" in html
        assert "NGN 58.00" in html
        # html in a name is escaped in the body and in the css footer
        assert "Acme &#34;Shoes&#34; &amp; Co" in html
        assert 'content: "Acme \\"Shoes\\" & Co' in html

    def test_unreadable_image_is_left_out(self):
        def broken(name: str) -> bytes:
            raise OSError("gone")

        html: str = evidence_html({"document": DOCUMENT, "files": FILES}, broken)
        assert "Supporting documents" not in html

    def test_images_are_resized(self):
        uri: str = prepare_image(_jpeg(2400, 1200))
        import base64

        image = Image.open(BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        assert image.size == (800, 400)


def _weasyprint_works() -> bool:
    try:
        from weasyprint import HTML

        HTML(string="<p>ok</p>").write_pdf()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _weasyprint_works(), reason="weasyprint needs pango (installed in ci)")
def test_real_pdf():
    from app.worker.services.evidence_pdf import render_pdf

    pdf: bytes = render_pdf(
        evidence_html({"document": DOCUMENT, "files": FILES}, lambda n: _jpeg())
    )
    assert pdf.startswith(b"%PDF")
