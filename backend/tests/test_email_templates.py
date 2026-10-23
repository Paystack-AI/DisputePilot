from datetime import UTC, date, datetime

from app.api.models.enums import OtpPurpose
from app.api.services.email_templates import (
    LOGO_CID,
    deadline_warning_email,
    dispute_alert_email,
    dispute_resolved_email,
    dispute_submitted_email,
    google_only_password_reset_email,
    otp_email,
    reconciliation_summary_email,
)
from app.core.config import get_settings

TOTALS: dict[str, int] = {
    "total_transactions": 15,
    "matched": 10,
    "suggested": 2,
    "unmatched_payments": 2,
    "unmatched_orders": 1,
    "flagged": 1,
}


def _frontend_url() -> str:
    return get_settings().FRONTEND_URL.rstrip("/")


class TestReconciliationSummary:
    def test_is_branded_with_the_frontend_logo(self):
        subject, html = reconciliation_summary_email(
            "Ada Stores", date(2026, 10, 1), date(2026, 10, 7), TOTALS
        )

        assert subject == "DisputePilot: Reconciliation for 01 Oct to 07 Oct 2026"
        assert f'src="cid:{LOGO_CID}"' in html
        assert f'href="{_frontend_url()}/reconciliation"' in html
        assert "Review reconciliation" in html

    def test_shows_the_counts_and_the_period(self):
        _, html = reconciliation_summary_email(
            "Ada Stores", date(2026, 10, 1), date(2026, 10, 7), TOTALS
        )

        assert "Reconciliation for <strong>Ada Stores</strong> is complete" in html
        assert "15 successful payments" in html
        assert "01 Oct to 07 Oct 2026" in html
        for label in (
            "Matched payments",
            "Suggested, awaiting confirmation",
            "Payments with no order",
            "Orders with no payment",
            "Flagged for review",
        ):
            assert label in html

    def test_escapes_the_business_name(self):
        _, html = reconciliation_summary_email(
            "Ada & Sons <Ltd>", date(2026, 10, 1), date(2026, 10, 1), TOTALS
        )

        assert "Ada &amp; Sons &lt;Ltd&gt;" in html
        assert "<Ltd>" not in html

    def test_single_day_period_and_one_payment(self):
        totals: dict[str, int] = {
            **TOTALS,
            "total_transactions": 1,
            "matched": 1,
            "suggested": 0,
            "unmatched_payments": 0,
            "unmatched_orders": 0,
            "flagged": 0,
        }
        subject, html = reconciliation_summary_email(
            "Ada Stores", date(2026, 10, 7), date(2026, 10, 7), totals
        )

        assert subject == "DisputePilot: Reconciliation for 07 Oct 2026"
        assert "1 successful payment</strong>" in html


class TestOtherEmails:
    def test_otp_email_has_the_code_and_logo(self):
        subject, html = otp_email(OtpPurpose.EMAIL_VERIFICATION, "123456", 15)

        assert subject == "DisputePilot: Verify your email"
        assert "123456" in html
        assert f'src="cid:{LOGO_CID}"' in html
        assert "expires in 15 minutes" in html

    def test_google_only_reset_links_to_sign_in(self):
        subject, html = google_only_password_reset_email()

        assert subject == "DisputePilot: Password reset requested"
        assert f'href="{_frontend_url()}/login"' in html
        assert "Continue with Google" in html

    def test_dispute_alert_escapes_and_formats_the_details(self):
        subject, html = dispute_alert_email(
            "Ada & Sons",
            123400,
            "NGN",
            "REF<1>",
            datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
        )

        assert subject == "DisputePilot: New dispute on REF<1>"
        assert "NGN 1,234.00" in html
        assert "REF&lt;1&gt;" in html
        assert "09 Oct 2026, 12:00 UTC" in html
        assert f'href="{_frontend_url()}/disputes"' in html

    def test_deadline_resolved_and_submitted_render(self):
        due_at: datetime = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

        for subject, html in (
            deadline_warning_email("REF-1", due_at),
            dispute_resolved_email("REF-1", "won"),
            dispute_submitted_email("REF-1", due_at),
        ):
            assert subject.startswith("DisputePilot: ")
            assert "REF-1" in html
            assert _frontend_url() in html
            assert "<table" in html
