import enum


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class ReconciliationStatus(enum.StrEnum):
    UNMATCHED = "unmatched"
    AUTO_MATCHED = "auto_matched"
    MANUALLY_MATCHED = "manually_matched"
    FLAGGED = "flagged"


class FulfillmentType(enum.StrEnum):
    DELIVERY = "delivery"
    SERVICE_COMPLETED = "service_completed"
    DIGITAL_DOWNLOAD = "digital_download"
    IN_STORE_PICKUP = "in_store_pickup"


class DisputeCategory(enum.StrEnum):
    CHARGEBACK_NO_VALUE = "chargeback_no_value"
    CHARGEBACK_NOT_AS_DESCRIBED = "chargeback_not_as_described"
    FRAUD = "fraud"
    ADMIN_ERROR = "admin_error"
    UNKNOWN = "unknown"


class SubmissionFlow(enum.StrEnum):
    CHARGEBACK_FLOW = "chargeback_flow"
    FRAUD_FLOW = "fraud_flow"


class DisputeStatus(enum.StrEnum):
    PENDING = "pending"
    EVIDENCE_GENERATED = "evidence_generated"
    SUBMITTED = "submitted"
    WON = "won"
    LOST = "lost"
    AUTO_ACCEPTED = "auto_accepted"


class EvidenceFileType(enum.StrEnum):
    RECEIPT = "receipt"
    DELIVERY_PHOTO = "delivery_photo"
    TRACKING_DOC = "tracking_doc"
    SIGNED_CONFIRMATION = "signed_confirmation"
    OTHER = "other"


class NotificationChannel(enum.StrEnum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class NotificationMessageType(enum.StrEnum):
    DISPUTE_ALERT = "dispute_alert"
    DEADLINE_WARNING = "deadline_warning"
    EVIDENCE_READY = "evidence_ready"
    RECONCILIATION_SUMMARY = "reconciliation_summary"
    DISPUTE_RESOLVED = "dispute_resolved"


class NotificationStatus(enum.StrEnum):
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"


class ReconciliationSessionStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TrustState(enum.StrEnum):
    VERIFIED = "verified"
    BUILDING = "building"
    NEW = "new"
    REVIEW = "review"


class Currency(enum.StrEnum):
    NGN = "NGN"
    USD = "USD"
    GHS = "GHS"
    ZAR = "ZAR"
    KES = "KES"
    XOF = "XOF"


class OrderSource(enum.StrEnum):
    WEBSITE = "website"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    IN_STORE = "in_store"
    OTHER = "other"


class TransactionChannel(enum.StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    USSD = "ussd"


class TransactionStatus(enum.StrEnum):
    FAILED = "failed"
    QUEUED = "queued"
    PENDING = "pending"
    ONGOING = "ongoing"
    SUCCESS = "success"
    REJECTED = "rejected"
    REVERSED = "reversed"
    INITIATED = "initiated"
    ABANDONED = "abandoned"
    PROCESSING = "processing"


class OtpPurpose(enum.StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # pragma: allowlist secret
    ACCOUNT_DEACTIVATION = "account_deactivation"
    ACCOUNT_REACTIVATION = "account_reactivation"


class GoogleSignInIntent(enum.StrEnum):
    SIGN_IN = "sign_in"
    REACTIVATE = "reactivate"


class GoogleSignInError(enum.StrEnum):
    """Sent back to the frontend as ?error= when google sign in can not complete"""

    ACCESS_DENIED = "access_denied"  # merchant cancelled on google's consent screen
    OAUTH_FAILED = "oauth_failed"  # state mismatch, expired session or google error
    EMAIL_NOT_VERIFIED = "google_email_not_verified"
    ACCOUNT_DEACTIVATED = "account_deactivated"


class UserType(enum.StrEnum):
    """How a session signed in; carried in its tokens as usertype"""

    EMAIL = "email"  # email and password
    GOOGLE = "google"
    EMAIL_CODE = "email_code"  # emailed code, e.g. reactivation; no password was used


class PaystackMode(enum.StrEnum):
    LIVE = "live"
    TEST = "test"


class OnboardingStep(enum.StrEnum):
    CONNECT_PAYSTACK = "connect_paystack"
    CONFIGURE_NOTIFICATIONS = "configure_notifications"
    INITIAL_SYNC = "initial_sync"
    FIRST_RECONCILIATION = "first_reconciliation"
    COMPLETED = "completed"


class InitialSyncStatus(enum.StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
