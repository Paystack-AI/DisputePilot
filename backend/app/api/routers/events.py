from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import sentry_sdk.logger as sentry_logger
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models.merchants import Merchant
from app.api.services.auth import AuthService
from app.api.services.events import event_stream
from app.core.config import get_settings
from app.core.exceptions import AppException, AuthenticationError, TooManyStreamsError
from app.core.security import Security
from app.database.session import get_session
from app.deps import AuthServiceDep, RedisDep, SecurityDep, bearer

SETTINGS = get_settings()

router = APIRouter()

# released as soon as the handler returns, before streaming starts, so a long-lived stream
# never holds a database connection
ShortDBSession = Annotated[AsyncSession, Depends(get_session, scope="function")]


def _connections_key(merchant_id: str) -> str:
    return f"events:connections:{merchant_id}"


def _connections_ttl() -> int:
    """A few heartbeats: refreshed on each, so it only lapses once no stream is alive"""
    return max(int(SETTINGS.EVENT_HEARTBEAT_SECONDS * 3), 1)


async def _authenticate(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    security: Security,
    auth_service: AuthService,
    session: AsyncSession,
) -> dict:
    """The access token from the Authorization header (the frontend proxy) or, failing
    that, the httponly cookie set at sign in (a browser EventSource calling the api
    directly). 401 when missing, expired or its session has ended"""
    token: str | None = (
        credentials.credentials
        if credentials
        else request.cookies.get(SETTINGS.ACCESS_TOKEN_COOKIE_NAME)
    )
    if not token:
        raise AuthenticationError()

    # raises TokenExpiredError (401 TOKEN_EXPIRED) for an expired token
    claims: dict | None = await security.decode_token(token, SETTINGS.ACCESS_TOKEN_SECRET_KEY)
    if not claims:
        raise AuthenticationError()

    await auth_service.verify_access_token(claims)

    merchant: Merchant | None = await session.get(Merchant, UUID(claims["sub"]))
    if not merchant or not merchant.is_verified or not merchant.is_active:
        raise AuthenticationError()

    return claims


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
    description=(
        "Live updates as server-sent events. Authenticate with the Authorization header "
        "(through the frontend proxy) or the access_token cookie. Sends Last-Event-ID back on "
        "reconnect to replay missed events; 'resync' means refetch everything. Ends with "
        "'session_expired' when the access token expires or the session ends: refresh and "
        "reconnect"
    ),
)
async def stream_events(
    request: Request,
    redis: RedisDep,
    security: SecurityDep,
    auth_service: AuthServiceDep,
    session: ShortDBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    claims: dict = await _authenticate(request, credentials, security, auth_service, session)
    merchant_id: str = claims["sub"]

    # cap open streams per merchant; the count expires if a process dies without releasing
    connections_key: str = _connections_key(merchant_id)
    open_streams: int = await redis.incr(connections_key)
    await redis.expire(connections_key, _connections_ttl())
    if open_streams > SETTINGS.EVENT_MAX_STREAMS_PER_MERCHANT:
        await redis.decr(connections_key)
        raise TooManyStreamsError(SETTINGS.EVENT_MAX_STREAMS_PER_MERCHANT)

    async def session_valid() -> bool:
        """The token has not expired and its session was not ended (logout, password
        change, deactivation); also keeps the connection count alive"""
        await redis.expire(connections_key, _connections_ttl())
        if datetime.now(UTC).timestamp() >= claims["exp"]:
            return False
        try:
            await auth_service.verify_access_token(claims)
        except AppException:
            return False
        return True

    async def body() -> AsyncIterator[str]:
        try:
            async for chunk in event_stream(
                redis,
                merchant_id,
                last_event_id,
                session_valid,
                heartbeat_seconds=SETTINGS.EVENT_HEARTBEAT_SECONDS,
            ):
                yield chunk
        finally:
            # the client went away, the session ended or the server is stopping
            await redis.decr(connections_key)
            sentry_logger.info(
                "Event stream closed for merchant {merchant_id}", merchant_id=merchant_id
            )

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx would otherwise buffer the stream and nothing would arrive
            "X-Accel-Buffering": "no",
        },
    )
