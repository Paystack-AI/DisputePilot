from datetime import date
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
