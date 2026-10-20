from datetime import date, datetime
from html import escape

from app.api.models.enums import OtpPurpose

# subject and the line that says what the code is for, per purpose
OTP_EMAILS: dict[OtpPurpose, tuple[str, str]] = {
    OtpPurpose.EMAIL_VERIFICATION: (
        "Verify your email",
        "Use this code to verify your email and finish signing up.",
    ),
    OtpPurpose.PASSWORD_RESET: (
        "Reset your password",
        "Use this code to reset your password.",
    ),
    OtpPurpose.ACCOUNT_DEACTIVATION: (
        "Confirm account deactivation",
        "Use this code to confirm you want to deactivate your account.",
    ),
    OtpPurpose.ACCOUNT_REACTIVATION: (
        "Reactivate your account",
        "Use this code to reactivate your account.",
    ),
}


def otp_email(purpose: OtpPurpose, code: str, expires_in_minutes: int) -> tuple[str, str]:
    """Subject and html body for a one-time code email"""
    subject, intro = OTP_EMAILS[purpose]
    html: str = (
        f"<p>{intro}</p>"
        f'<p style="font-size:24px;font-weight:bold;letter-spacing:4px">{code}</p>'
        f"<p>The code expires in {expires_in_minutes} minutes. "
        "If you did not request it, you can ignore this email.</p>"
    )
    return f"DisputePilot: {subject}", html


def google_only_password_reset_email() -> tuple[str, str]:
    """Sent instead of a reset code when the account has no password"""
    html: str = (
        "<p>Someone asked to reset the password for this DisputePilot account.</p>"
        "<p>This account signs in with Google and has no password to reset. "
        "Use <strong>Continue with Google</strong> on the sign in page instead.</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
    )
    return "DisputePilot: Password reset requested", html


def reconciliation_summary_email(
    business_name: str, date_range_start: date, date_range_end: date, totals: dict[str, int]
) -> tuple[str, str]:
    """Sent when the merchant completes a reconciliation session"""
    period: str = (
        date_range_start.strftime("%d %b %Y")
        if date_range_start == date_range_end
        else f"{date_range_start:%d %b} to {date_range_end:%d %b %Y}"
    )
    rows: str = "".join(
        f'<tr><td style="padding:4px 16px 4px 0">{label}</td>'
        f'<td style="padding:4px 0"><strong>{totals[key]}</strong></td></tr>'
        for key, label in (
            ("matched", "Matched"),
            ("suggested", "Suggested, not confirmed"),
            ("unmatched_payments", "Payments with no order"),
            ("unmatched_orders", "Orders with no payment"),
            ("flagged", "Flagged for review"),
        )
    )
    html: str = (
        f"<p>Reconciliation for <strong>{escape(business_name)}</strong>, {period}, "
        "is complete.</p>"
        f"<p>{totals['total_transactions']} successful payments in the period.</p>"
        f"<table>{rows}</table>"
        "<p>Open DisputePilot to resolve anything left over. Matched payments with fulfillment "
        "records are the strongest defence if a customer disputes them.</p>"
    )
    return f"DisputePilot: Reconciliation for {period}", html


def _money(amount: int, currency: str) -> str:
    return f"{currency} {amount / 100:,.2f}"


def dispute_alert_email(
    business_name: str, amount: int, currency: str, reference: str, due_at: datetime
) -> tuple[str, str]:
    """A customer opened a dispute"""
    html: str = (
        f"<p>A customer has disputed a payment to <strong>{escape(business_name)}</strong>.</p>"
        f"<p>Payment <strong>{escape(reference)}</strong>, {_money(amount, currency)}.</p>"
        f"<p>Respond by <strong>{due_at:%d %b %Y, %H:%M} UTC</strong>, or Paystack refunds "
        "the customer automatically.</p>"
        "<p>Open DisputePilot to generate the evidence and respond.</p>"
    )
    return f"DisputePilot: New dispute on {reference}", html


def deadline_warning_email(reference: str, due_at: datetime) -> tuple[str, str]:
    """Paystack's reminder that the response deadline is close"""
    html: str = (
        f"<p>The dispute on payment <strong>{escape(reference)}</strong> still needs a "
        f"response. The deadline is <strong>{due_at:%d %b %Y, %H:%M} UTC</strong>.</p>"
        "<p>Without a response Paystack refunds the customer automatically.</p>"
    )
    return f"DisputePilot: Dispute deadline approaching for {reference}", html


def dispute_resolved_email(reference: str, outcome: str) -> tuple[str, str]:
    """The dispute was closed; outcome is won, lost or auto_accepted"""
    lines: dict[str, str] = {
        "won": "was resolved in your favour. No refund is due.",
        "lost": "was resolved in the customer's favour and the payment is refunded.",
        "auto_accepted": "was not answered before the deadline, so the customer was refunded.",
    }
    html: str = (
        f"<p>The dispute on payment <strong>{escape(reference)}</strong> "
        f"{lines.get(outcome, 'has been resolved.')}</p>"
    )
    return f"DisputePilot: Dispute on {reference} resolved", html
