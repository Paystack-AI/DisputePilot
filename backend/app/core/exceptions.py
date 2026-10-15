from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse


class AppException(Exception):
    """Base Exception class"""

    def __init__(self, code: str):
        self.code = code


class ServerError(AppException):
    pass


class RateLimitExceeded(AppException):
    def __init__(self, retry_after: int):
        super().__init__("RATE_LIMITED")
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


def exception_handler(
    code: int, detail: dict
) -> Callable[[Request, AppException], Awaitable[JSONResponse]]:
    async def _handler(request: Request, exc: AppException):
        message = detail.get("message").format(**exc.__dict__)
        error = Error(
            code=exc.code or detail.get("code"),
            message=message,
            request_id=request.state.request_id,
        )

        content = ErrorResponse(error=error)
        return JSONResponse(
            content=content.model_dump(mode="json"),
            status_code=code,
            headers=getattr(exc, "headers", None),
        )

    return _handler
