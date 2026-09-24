from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.schemas.response import Error, ErrorResponse


class AppException(Exception):
    """Base Exception class"""

    pass


class ServerError(AppException):
    pass


def exception_handler(
    code: int, detail: dict
) -> Callable[[Request, AppException], Awaitable[JSONResponse]]:
    async def _handler(request: Request, exc: AppException):
        message = detail.get("message").format(**exc.__dict__)

        content = ErrorResponse(error=Error(detail.get("code"), message, request.state.request_id))
        return JSONResponse(content=content.model_dump(mode="json"), status_code=code)

    return _handler
