import asyncio
import base64
import json

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.api.services.auth import AuthService
from app.api.services.events import event_stream, publish_event, stream_key
from app.core.config import get_settings

SETTINGS = get_settings()
MERCHANT_ID = "6f1c2c1e-1111-4a4a-9b9b-000000000001"


async def _valid() -> bool:
    return True


async def _invalid() -> bool:
    return False


def _parse(chunks: list[str]) -> list[dict]:
    """Server-sent events (comments and the retry line skipped) as dicts"""
    events: list[dict] = []
    for chunk in chunks:
        for block in chunk.split("\n\n"):
            if not block or block.startswith(":") or block.startswith("retry:"):
                continue
            event: dict = {}
            for line in block.split("\n"):
                name, _, value = line.partition(": ")
                event[name] = json.loads(value) if name == "data" else value
            events.append(event)
    return events


async def _collect(stream, until: int) -> list[str]:
    """Reads chunks until `until` events (not comments) have arrived"""
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
        if len(_parse(chunks)) >= until:
            break
    await stream.aclose()
    return chunks


def _merchant_id(login: Response) -> str:
    payload: str = login.json()["data"]["access_token"].split(".")[1]
    claims: dict = json.loads(base64.urlsafe_b64decode(payload + "=="))
    return claims["sub"]


class TestEventStream:
    @pytest.mark.asyncio
    async def test_starts_with_retry(self, test_redis_client: Redis):
        stream = event_stream(test_redis_client, MERCHANT_ID, None, _valid, heartbeat_seconds=0.05)
        assert await anext(stream) == "retry: 3000\n\n"
        await stream.aclose()

    @pytest.mark.asyncio
    async def test_fresh_connection_gets_only_new_events(self, test_redis_client: Redis):
        await publish_event(test_redis_client, MERCHANT_ID, "old", {"n": 0})
        stream = event_stream(test_redis_client, MERCHANT_ID, None, _valid, heartbeat_seconds=0.05)
        await anext(stream)

        async def later():
            await asyncio.sleep(0.02)
            return await publish_event(test_redis_client, MERCHANT_ID, "order.updated", {"n": 1})

        publish = asyncio.create_task(later())
        events: list[dict] = _parse(await _collect(stream, 1))
        new_id: str = await publish

        assert events == [{"id": new_id, "event": "order.updated", "data": {"n": 1}}]

    @pytest.mark.asyncio
    async def test_replays_after_last_event_id(self, test_redis_client: Redis):
        first: str = await publish_event(test_redis_client, MERCHANT_ID, "a", {"n": 1})
        second: str = await publish_event(test_redis_client, MERCHANT_ID, "b", {"n": 2})
        third: str = await publish_event(test_redis_client, MERCHANT_ID, "c", {"n": 3})

        stream = event_stream(test_redis_client, MERCHANT_ID, first, _valid, heartbeat_seconds=0.05)
        events: list[dict] = _parse(await _collect(stream, 2))

        assert [e["id"] for e in events] == [second, third]
        assert [e["event"] for e in events] == ["b", "c"]

    @pytest.mark.asyncio
    async def test_resync_when_stream_expired(self, test_redis_client: Redis):
        stream = event_stream(
            test_redis_client, MERCHANT_ID, "1700000000000-0", _valid, heartbeat_seconds=0.05
        )
        events: list[dict] = _parse(await _collect(stream, 1))
        assert events[0]["event"] == "resync"

    @pytest.mark.asyncio
    async def test_resync_when_missed_events_trimmed(self, test_redis_client: Redis):
        for n in range(3):
            await publish_event(test_redis_client, MERCHANT_ID, "a", {"n": n})
        oldest: str = (await test_redis_client.xrange(stream_key(MERCHANT_ID), count=1))[0][0]
        await test_redis_client.xdel(stream_key(MERCHANT_ID), oldest)

        stream = event_stream(
            test_redis_client, MERCHANT_ID, oldest, _valid, heartbeat_seconds=0.05
        )
        events: list[dict] = _parse(await _collect(stream, 1))
        assert events[0]["event"] == "resync"

    @pytest.mark.asyncio
    async def test_resync_for_unknown_future_id(self, test_redis_client: Redis):
        await publish_event(test_redis_client, MERCHANT_ID, "a", {})
        stream = event_stream(
            test_redis_client, MERCHANT_ID, "99999999999999-0", _valid, heartbeat_seconds=0.05
        )
        events: list[dict] = _parse(await _collect(stream, 1))
        assert events[0]["event"] == "resync"

    @pytest.mark.asyncio
    async def test_malformed_last_event_id_is_a_fresh_connection(self, test_redis_client: Redis):
        await publish_event(test_redis_client, MERCHANT_ID, "a", {})
        stream = event_stream(
            test_redis_client, MERCHANT_ID, "nonsense", _valid, heartbeat_seconds=0.05
        )
        await anext(stream)
        # nothing to replay, no resync: the next thing is a heartbeat
        assert await anext(stream) == ": ping\n\n"
        await stream.aclose()

    @pytest.mark.asyncio
    async def test_ends_with_session_expired(self, test_redis_client: Redis):
        stream = event_stream(
            test_redis_client, MERCHANT_ID, None, _invalid, heartbeat_seconds=0.05
        )
        chunks: list[str] = [chunk async for chunk in stream]
        assert _parse(chunks) == [{"event": "session_expired", "data": {}}]

    @pytest.mark.asyncio
    async def test_publish_caps_and_expires_stream(self, test_redis_client: Redis):
        await publish_event(test_redis_client, MERCHANT_ID, "a", {})
        ttl: int = await test_redis_client.ttl(stream_key(MERCHANT_ID))
        assert 0 < ttl <= SETTINGS.EVENT_STREAM_TTL_SECONDS


class TestEventsEndpoint:
    @pytest.mark.asyncio
    async def test_no_token(self, async_client: AsyncClient):
        res: Response = await async_client.get("/events")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_token(self, async_client: AsyncClient):
        res: Response = await async_client.get(
            "/events", headers={"Authorization": "Bearer not-a-token"}
        )
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_cookie(self, async_client: AsyncClient):
        async_client.cookies.set(SETTINGS.ACCESS_TOKEN_COOKIE_NAME, "not-a-token")
        res: Response = await async_client.get("/events")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_too_many_streams(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        login: Response,
        test_redis_client: Redis,
    ):
        key: str = f"events:connections:{_merchant_id(login)}"
        await test_redis_client.set(key, SETTINGS.EVENT_MAX_STREAMS_PER_MERCHANT)

        res: Response = await async_client.get("/events", headers=auth_headers)

        assert res.status_code == 429
        assert res.json()["error"]["code"] == "TOO_MANY_STREAMS"
        # the rejected connection is not counted
        assert int(await test_redis_client.get(key)) == SETTINGS.EVENT_MAX_STREAMS_PER_MERCHANT

    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_cookie", [False, True])
    async def test_streams_until_session_ends(
        self,
        async_client: AsyncClient,
        login: Response,
        test_redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        with_cookie: bool,
    ):
        monkeypatch.setattr(SETTINGS, "EVENT_HEARTBEAT_SECONDS", 0.05)
        merchant_id: str = _merchant_id(login)
        token: str = login.json()["data"]["access_token"]
        if with_cookie:
            # login set it; the header is not sent
            assert async_client.cookies.get(SETTINGS.ACCESS_TOKEN_COOKIE_NAME) == token
            headers: dict = {}
        else:
            async_client.cookies.clear()
            headers = {"Authorization": f"Bearer {token}"}

        before: str = await publish_event(test_redis_client, merchant_id, "a", {"n": 1})
        await publish_event(test_redis_client, merchant_id, "b", {"n": 2})

        async def end_session():
            await asyncio.sleep(0.2)
            await test_redis_client.delete(AuthService._sessions_key(merchant_id))

        ender = asyncio.create_task(end_session())
        res: Response = await async_client.get(
            "/events", headers={**headers, "Last-Event-ID": before}
        )
        await ender

        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        assert res.headers["cache-control"] == "no-cache"
        events: list[dict] = _parse([res.text])
        assert [e["event"] for e in events] == ["b", "session_expired"]
        assert ": ping" in res.text
        # the connection was released
        assert int(await test_redis_client.get(f"events:connections:{merchant_id}")) == 0


class TestAccessTokenCookie:
    @pytest.mark.asyncio
    async def test_login_sets_httponly_cookie(self, login: Response):
        cookie: str = login.headers["set-cookie"]
        assert cookie.startswith(f"{SETTINGS.ACCESS_TOKEN_COOKIE_NAME}=")
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie

    @pytest.mark.asyncio
    async def test_refresh_sets_cookie(self, async_client: AsyncClient, login: Response):
        res: Response = await async_client.post(
            "/auth/refresh", json={"refresh_token": login.json()["data"]["refresh_token"]}
        )
        assert res.status_code == 200
        assert (
            async_client.cookies.get(SETTINGS.ACCESS_TOKEN_COOKIE_NAME)
            == (res.json()["data"]["access_token"])
        )

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.post("/auth/logout", headers=auth_headers)
        assert res.status_code == 204
        assert async_client.cookies.get(SETTINGS.ACCESS_TOKEN_COOKIE_NAME) is None


class TestCors:
    @pytest.mark.asyncio
    async def test_preflight_from_allowed_origin(self, async_client: AsyncClient):
        origin: str = SETTINGS.CORS_ALLOWED_ORIGINS.split(",")[0].strip()
        res: Response = await async_client.options(
            "/events",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Last-Event-ID",
            },
        )
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == origin
        assert res.headers["access-control-allow-credentials"] == "true"

    @pytest.mark.asyncio
    async def test_preflight_from_other_origin(self, async_client: AsyncClient):
        res: Response = await async_client.options(
            "/events",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in res.headers
