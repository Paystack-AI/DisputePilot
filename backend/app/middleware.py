from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate a unique id for each receievd request"""

    async def dispatch(self, request, call_next):
        request_id = uuid4()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = str(request_id)
        return response
