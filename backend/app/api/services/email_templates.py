"""Subject and html for every email the product sends.

All templates share one branded shell so the inbox stays consistent: logo, card,
heading, optional detail table, call to action, and a footer with notification settings.
The layout is table based and uses inline styles, which is what email clients support.
"""

from datetime import date, datetime
from html import escape

from app.api.models.enums import OtpPurpose
from app.core.config import get_settings

# frontend palette, so the emails match the product
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
INK_900 = "#0f172a"
INK_700 = "#334155"
INK_500 = "#64748b"
INK_200 = "#e2e6ec"
INK_50 = "#f7f8fa"
BRAND_600 = "#1d57eb"

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


def _app_url() -> str:
    return get_settings().FRONTEND_URL.rstrip("/")


def _paragraph(text: str, muted: bool = False) -> str:
    color: str = INK_500 if muted else INK_700
    return (
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:15px;line-height:1.65;'
        f'color:{color}">{text}</p>'
    )


def _button(label: str, path: str) -> str:
    url: str = f"{_app_url()}{path}"
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:26px 0 2px">'
        '<tr><td style="background:#1d57eb;border-radius:10px">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:13px 24px;'
        f"font-family:{FONT};font-size:14px;font-weight:600;color:#ffffff;"
        'text-decoration:none;border-radius:10px">'
        f"{escape(label)}</a>"
        "</td></tr></table>"
    )


def _detail_table(rows: list[tuple[str, str]]) -> str:
    cells: str = "".join(
        f"<tr>"
        f'<td style="padding:12px 0;{"" if index == 0 else f"border-top:1px solid {INK_200};"}'
        f'font-family:{FONT};font-size:14px;line-height:1.4;color:{INK_500}">{label}</td>'
        f'<td align="right" style="padding:12px 0 12px 16px;'
        f"{'' if index == 0 else f'border-top:1px solid {INK_200};'}"
        f"font-family:{FONT};font-size:14px;line-height:1.4;font-weight:600;"
        f'color:{INK_900}">{value}</td>'
        f"</tr>"
        for index, (label, value) in enumerate(rows)
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:20px 0 22px">{cells}</table>'
    )


def _code_block(code: str) -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:22px 0">'
        f'<tr><td align="center" style="background:{INK_50};border:1px solid {INK_200};'
        f"border-radius:12px;padding:18px 20px;font-family:{FONT};font-size:30px;"
        f'font-weight:700;letter-spacing:8px;color:{INK_900}">{escape(code)}</td></tr>'
        "</table>"
    )


def _layout(
    *,
    heading: str,
    body: str,
    preheader: str,
    eyebrow: str | None = None,
    cta_label: str | None = None,
    cta_path: str | None = None,
    footer_note: str | None = None,
) -> str:
    app_url: str = _app_url()
    logo_url: str = f"{app_url}/logo.png"
    eyebrow_html: str = (
        f'<p style="margin:0 0 10px;font-family:{FONT};font-size:11px;font-weight:700;'
        f'letter-spacing:1.4px;text-transform:uppercase;color:{BRAND_600}">{escape(eyebrow)}</p>'
        if eyebrow
        else ""
    )
    cta_html: str = _button(cta_label, cta_path) if cta_label and cta_path else ""
    footer_note_html: str = f'<p style="margin:0 0 8px">{footer_note}</p>' if footer_note else ""
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        f"<title>{escape(heading)}</title>"
        "</head>"
        f'<body style="margin:0;padding:0;background:{INK_50}">'
        f'<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;'
        f'opacity:0;overflow:hidden;color:{INK_50}">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{INK_50}">'
        '<tr><td align="center" style="padding:40px 16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px">'
        # brand
        '<tr><td style="padding:0 4px 20px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="vertical-align:middle;padding-right:10px">'
        f'<img src="{escape(logo_url)}" width="32" height="32" alt="DisputePilot" '
        'style="display:block;border:0;border-radius:8px">'
        "</td>"
        f'<td style="vertical-align:middle;font-family:{FONT};font-size:16px;font-weight:700;'
        f'letter-spacing:-0.2px;color:{INK_900}">DisputePilot</td>'
        "</tr></table>"
        "</td></tr>"
        # card
        '<tr><td style="background:#ffffff;border:1px solid '
        f'{INK_200};border-radius:16px;padding:36px 36px 32px">'
        f"{eyebrow_html}"
        f'<h1 style="margin:0 0 16px;font-family:{FONT};font-size:21px;line-height:1.3;'
        f'font-weight:700;letter-spacing:-0.3px;color:{INK_900}">{escape(heading)}</h1>'
        f"{body}"
        f"{cta_html}"
        "</td></tr>"
        # footer
        f'<tr><td style="padding:22px 8px 0;font-family:{FONT};font-size:12px;'
        f'line-height:1.6;color:{INK_500}">'
        f"{footer_note_html}"
        '<p style="margin:0 0 6px">You are receiving this email because email notifications '
        "are on for your DisputePilot account.</p>"
        f'<p style="margin:0">DisputePilot &middot; '
        f'<a href="{escape(app_url)}/settings" style="color:{INK_500};text-decoration:underline">'
        "Notification settings</a></p>"
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body>"
        "</html>"
    )


def otp_email(purpose: OtpPurpose, code: str, expires_in_minutes: int) -> tuple[str, str]:
    """Subject and html body for a one-time code email"""
    subject, intro = OTP_EMAILS[purpose]
    html: str = _layout(
        heading=subject,
        preheader=intro,
        body=(
            _paragraph(escape(intro))
            + _code_block(code)
            + _paragraph(
                f"This code expires in {expires_in_minutes} minutes. "
                "If you did not request it, you can ignore this email.",
                muted=True,
            )
        ),
    )
    return f"DisputePilot: {subject}", html


def google_only_password_reset_email() -> tuple[str, str]:
    """Sent instead of a reset code when the account has no password"""
    html: str = _layout(
        heading="Password reset requested",
        preheader="This account signs in with Google and has no password to reset.",
        body=(
            _paragraph("Someone asked to reset the password for this DisputePilot account.")
            + _paragraph(
                "This account signs in with Google and has no password to reset. "
                "Use <strong>Continue with Google</strong> on the sign in page instead."
            )
            + _paragraph("If you did not request this, you can ignore this email.", muted=True)
        ),
        cta_label="Sign in to DisputePilot",
        cta_path="/login",
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
    payments: int = totals["total_transactions"]
    payments_label: str = f"{payments} successful payment{'s' if payments != 1 else ''}"
    rows: list[tuple[str, str]] = [
        ("Matched payments", str(totals["matched"])),
        ("Suggested, awaiting confirmation", str(totals["suggested"])),
        ("Payments with no order", str(totals["unmatched_payments"])),
        ("Orders with no payment", str(totals["unmatched_orders"])),
        ("Flagged for review", str(totals["flagged"])),
    ]
    html: str = _layout(
        eyebrow="Reconciliation complete",
        heading="Your reconciliation is complete",
        preheader=f"{totals['matched']} of {payments} payments matched for {period}.",
        body=(
            _paragraph(
                f"Reconciliation for <strong>{escape(business_name)}</strong> is complete. "
                f"We reviewed <strong>{payments_label}</strong> from {escape(period)}."
            )
            + _detail_table(rows)
            + _paragraph(
                "Anything still open is waiting for review. Confirming suggested matches and "
                "adding fulfillment records gives you the strongest evidence if a customer "
                "disputes a payment.",
                muted=True,
            )
        ),
        cta_label="Review reconciliation",
        cta_path="/reconciliation",
        footer_note=f"Sent to the team at <strong>{escape(business_name)}</strong>.",
    )
    return f"DisputePilot: Reconciliation for {period}", html


def _money(amount: int, currency: str) -> str:
    return f"{escape(currency)} {amount / 100:,.2f}"


def dispute_alert_email(
    business_name: str, amount: int, currency: str, reference: str, due_at: datetime
) -> tuple[str, str]:
    """A customer opened a dispute"""
    deadline: str = f"{due_at:%d %b %Y, %H:%M} UTC"
    html: str = _layout(
        eyebrow="New dispute",
        heading="A customer disputed a payment",
        preheader=f"Payment {reference} needs a response by {deadline}.",
        body=(
            _paragraph(
                f"A customer has disputed a payment to <strong>{escape(business_name)}</strong>."
            )
            + _detail_table(
                [
                    ("Payment reference", escape(reference)),
                    ("Amount", _money(amount, currency)),
                    ("Respond by", escape(deadline)),
                ]
            )
            + _paragraph(
                "If you do not respond by the deadline, Paystack refunds the customer "
                "automatically.",
                muted=True,
            )
        ),
        cta_label="Respond to dispute",
        cta_path="/disputes",
    )
    return f"DisputePilot: New dispute on {reference}", html


def deadline_warning_email(reference: str, due_at: datetime) -> tuple[str, str]:
    """Paystack's reminder that the response deadline is close"""
    deadline: str = f"{due_at:%d %b %Y, %H:%M} UTC"
    html: str = _layout(
        eyebrow="Deadline approaching",
        heading="This dispute still needs a response",
        preheader=f"Payment {reference} must be answered by {deadline}.",
        body=(
            _paragraph(
                f"The dispute on payment <strong>{escape(reference)}</strong> still needs a "
                "response. Without one, Paystack refunds the customer automatically."
            )
            + _detail_table(
                [
                    ("Payment reference", escape(reference)),
                    ("Deadline", escape(deadline)),
                ]
            )
        ),
        cta_label="Respond now",
        cta_path="/disputes",
    )
    return f"DisputePilot: Dispute deadline approaching for {reference}", html


def dispute_resolved_email(reference: str, outcome: str) -> tuple[str, str]:
    """The dispute was closed; outcome is won, lost or auto_accepted"""
    lines: dict[str, str] = {
        "won": "was resolved in your favour. No refund is due.",
        "lost": "was resolved in the customer's favour and the payment is refunded.",
        "auto_accepted": "was not answered before the deadline, so the customer was refunded.",
    }
    html: str = _layout(
        eyebrow="Dispute closed",
        heading="The dispute has been resolved",
        preheader=f"The dispute on payment {reference} is closed.",
        body=(
            _paragraph(
                f"The dispute on payment <strong>{escape(reference)}</strong> "
                f"{lines.get(outcome, 'has been resolved.')}"
            )
            + _detail_table(
                [
                    ("Payment reference", escape(reference)),
                    ("Outcome", escape(outcome.replace("_", " ").capitalize())),
                ]
            )
        ),
        cta_label="View dispute",
        cta_path="/disputes",
    )
    return f"DisputePilot: Dispute on {reference} resolved", html


def dispute_submitted_email(reference: str, due_at: datetime) -> tuple[str, str]:
    """The response went to paystack; the evidence pdf is attached"""
    deadline: str = f"{due_at:%d %b %Y, %H:%M} UTC"
    html: str = _layout(
        eyebrow="Response submitted",
        heading="Your evidence is with Paystack",
        preheader=f"Your response to the dispute on {reference} was submitted.",
        body=(
            _paragraph(
                f"Your response to the dispute on payment <strong>{escape(reference)}</strong> "
                "was submitted to Paystack with the attached evidence."
            )
            + _detail_table(
                [
                    ("Payment reference", escape(reference)),
                    ("Submitted before", escape(deadline)),
                ]
            )
            + _paragraph(
                "The bank now reviews it; you will hear from us as soon as it is resolved.",
                muted=True,
            )
        ),
        cta_label="View dispute",
        cta_path="/disputes",
    )
    return f"DisputePilot: Response submitted for {reference}", html
