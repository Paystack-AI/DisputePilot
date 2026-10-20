from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse
from app.core.exceptions import (
    AccountDeactivatedError,
    AuthenticationError,
    CredentialError,
    CustomerEmailLockedError,
    CustomerExistsError,
    EmailNotVerifiedError,
    FileAlreadyAttachedError,
    InvalidOAuthCodeError,
    InvalidOtpError,
    MatchConflictError,
    MerchantExistsError,
    NotFoundError,
    OnboardingStepMismatchError,
    OrderLinkedError,
    OrderNumberExistsError,
    OrderStatusTransitionError,
    OtpAttemptsExceededError,
    PasswordLoginRequiredError,
    PayloadTooLargeError,
    PaystackIntegrationMismatchError,
    PaystackKeyInvalidError,
    PaystackNotConnectedError,
    PaystackUpstreamError,
    RateLimitExceeded,
    ServerError,
    StorageUpstreamError,
    SyncInProgressError,
    TokenExpiredError,
    TooManyStreamsError,
    UnsupportedFileTypeError,
    WebhookSignatureError,
    exception_handler,
)


class ExceptionHandler:
    def __init__(self, app: FastAPI):
        self.app = app

    def override_validation_handler(self):
        @self.app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            details = {".".join(str(x) for x in err["loc"][1:]): err["msg"] for err in exc.errors()}

            return JSONResponse(
                content=ErrorResponse(
                    error=Error(
                        code="VALIDATION_FAILED",
                        message="Some fields are missing or invalid. See details.",
                        request_id=request.state.request_id,
                        details=details,
                    )
                ).model_dump(mode="json"),
                status_code=422,
            )

    def include_handlers(self):
        self.app.add_exception_handler(
            ServerError,
            exception_handler(
                500,
                {"message": "Internal server error occured while processing request"},
            ),
        )
        self.app.add_exception_handler(
            AuthenticationError,
            exception_handler(401, {"message": "Merchant not authenticated."}),
        )
        self.app.add_exception_handler(
            TokenExpiredError,
            exception_handler(401, {"message": "Token has expired."}),
        )
        self.app.add_exception_handler(
            CredentialError,
            exception_handler(400, {"message": "Invalid credentials!"}),
        )
        self.app.add_exception_handler(
            MerchantExistsError,
            exception_handler(
                409,
                {"message": "A merchant already exists with the provided details."},
            ),
        )
        self.app.add_exception_handler(
            InvalidOtpError,
            exception_handler(400, {"message": "Invalid or expired code."}),
        )
        self.app.add_exception_handler(
            OtpAttemptsExceededError,
            exception_handler(
                400, {"message": "Too many wrong attempts. Request a new code to continue."}
            ),
        )
        self.app.add_exception_handler(
            EmailNotVerifiedError,
            exception_handler(403, {"message": "Verify your email to continue."}),
        )
        self.app.add_exception_handler(
            AccountDeactivatedError,
            exception_handler(
                403, {"message": "This account is deactivated. Reactivate it to continue."}
            ),
        )
        self.app.add_exception_handler(
            InvalidOAuthCodeError,
            exception_handler(
                400, {"message": "This sign in link has expired. Sign in with Google again."}
            ),
        )
        self.app.add_exception_handler(
            PasswordLoginRequiredError,
            exception_handler(
                403,
                {"message": "Sign in with your email and password to change your password."},
            ),
        )
        self.app.add_exception_handler(
            OnboardingStepMismatchError,
            exception_handler(
                409,
                {"message": "This onboarding step is not available from {current_step}."},
            ),
        )
        self.app.add_exception_handler(
            NotFoundError,
            exception_handler(404, {"message": "{resource} not found."}),
        )
        self.app.add_exception_handler(
            CustomerExistsError,
            exception_handler(409, {"message": "A customer with this email already exists."}),
        )
        self.app.add_exception_handler(
            CustomerEmailLockedError,
            exception_handler(
                409,
                {"message": "This customer has synced payments, so their email can not change."},
            ),
        )
        self.app.add_exception_handler(
            OrderNumberExistsError,
            exception_handler(409, {"message": "An order with this number already exists."}),
        )
        self.app.add_exception_handler(
            OrderLinkedError,
            exception_handler(
                409,
                {
                    "message": "This order is linked to a payment. Unlink it in reconciliation "
                    "to change it."
                },
            ),
        )
        self.app.add_exception_handler(
            OrderStatusTransitionError,
            exception_handler(
                409, {"message": "An order can not move from {current_status} to {new_status}."}
            ),
        )
        self.app.add_exception_handler(
            MatchConflictError,
            exception_handler(409, {"message": "This payment can not be matched to that order."}),
        )
        self.app.add_exception_handler(
            PaystackNotConnectedError,
            exception_handler(422, {"message": "Connect your Paystack account to continue."}),
        )
        self.app.add_exception_handler(
            SyncInProgressError,
            exception_handler(
                409, {"message": "Your first sync is still running. Try again once it finishes."}
            ),
        )
        self.app.add_exception_handler(
            PaystackKeyInvalidError,
            exception_handler(422, {"message": "Paystack rejected this secret key."}),
        )
        self.app.add_exception_handler(
            PaystackIntegrationMismatchError,
            exception_handler(
                409,
                {
                    "message": "This key belongs to a different Paystack account than the one "
                    "connected."
                },
            ),
        )
        self.app.add_exception_handler(
            PaystackUpstreamError,
            exception_handler(
                502, {"message": "Paystack could not be reached. Try again shortly."}
            ),
        )
        self.app.add_exception_handler(
            StorageUpstreamError,
            exception_handler(
                502, {"message": "File storage could not be reached. Try again shortly."}
            ),
        )
        self.app.add_exception_handler(
            PayloadTooLargeError,
            exception_handler(413, {"message": "Uploads are limited to {limit_mb} MB per file."}),
        )
        self.app.add_exception_handler(
            UnsupportedFileTypeError,
            exception_handler(
                415, {"message": "Only JPEG, PNG, WebP and HEIC images can be uploaded."}
            ),
        )
        self.app.add_exception_handler(
            FileAlreadyAttachedError,
            exception_handler(409, {"message": "This file is already attached to another record."}),
        )
        self.app.add_exception_handler(
            TooManyStreamsError,
            exception_handler(
                429,
                {
                    "message": "Live updates are open in {limit} places already. Close one "
                    "and try again."
                },
            ),
        )
        self.app.add_exception_handler(
            WebhookSignatureError,
            exception_handler(401, {"message": "Invalid webhook signature."}),
        )
        self.app.add_exception_handler(
            RateLimitExceeded,
            exception_handler(
                429,
                {"message": "Too many requests. Try again in {retry_after} seconds."},
            ),
        )
