from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse
from app.core.exceptions import (
    AccountDeactivatedError,
    AuthenticationError,
    CredentialError,
    EmailNotVerifiedError,
    InvalidOAuthCodeError,
    InvalidOtpError,
    MerchantExistsError,
    OnboardingStepMismatchError,
    OtpAttemptsExceededError,
    PasswordLoginRequiredError,
    RateLimitExceeded,
    ServerError,
    TokenExpiredError,
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
                        message="",
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
            RateLimitExceeded,
            exception_handler(
                429,
                {"message": "Too many requests. Try again in {retry_after} seconds."},
            ),
        )
