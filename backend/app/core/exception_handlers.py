from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse
from app.core.exceptions import RateLimitExceeded, ServerError, exception_handler


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
            RateLimitExceeded,
            exception_handler(
                429,
                {"message": "Too many requests. Try again in {retry_after} seconds."},
            ),
        )
