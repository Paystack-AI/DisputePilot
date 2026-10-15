from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    AsyncTransaction,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api import models  # noqa: F401
from app.api.models.base import Base
from app.api.services.otp import OtpService
from app.core.config import get_settings
from app.database.session import get_session
from app.deps import get_redis_client, read_limiter, write_limiter
from app.main import app

# keep test keys away from the dev data in the default redis db
TEST_REDIS_URL: str = get_settings().REDIS_URL.rsplit("/", 1)[0] + "/15"

OTP_CODE: str = "123456"

# test-only credentials
NEW_PASSWORD: str = "new_merchant_password"  # pragma: allowlist secret
WRONG_PASSWORD: str = "wrong_password"  # pragma: allowlist secret

SIGN_UP_PAYLOAD: dict = {
    "email": "merchant@example.com",
    "password": "merchant_password",  # pragma: allowlist secret
    "business_name": "Acme Store",
}


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    async_db_engine: AsyncEngine = create_async_engine(
        url=get_settings().ASYNC_TEST_DB_URL, poolclass=NullPool
    )

    async with async_db_engine.begin() as conn:
        await conn.execute(
            text("""
            CREATE OR REPLACE FUNCTION uuid_generate_v7()
                RETURNS UUID
                LANGUAGE SQL
                VOLATILE
                AS $$
                    SELECT encode(
                        set_bit(
                            set_bit(
                                overlay(
                                    uuid_send(gen_random_uuid())
                                    placing substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                                    FROM 1 FOR 6
                                ),
                                52, 1
                            ),
                            53, 1
                        ),
                        'hex'
                    )::uuid
                $$;
        """)  # noqa: E501
        )
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield async_db_engine

    async with async_db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP FUNCTION IF EXISTS uuid_generate_v7 CASCADE"))

    await async_db_engine.dispose()


@pytest_asyncio.fixture
async def session_maker(async_engine: AsyncEngine):
    async_connection: AsyncConnection = await async_engine.connect()
    async_transaction: AsyncTransaction = await async_connection.begin()

    # commits inside the app only release a savepoint; everything is rolled back after the test
    session = async_sessionmaker(
        bind=async_connection,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    yield session

    await async_transaction.rollback()
    await async_connection.close()


@pytest_asyncio.fixture
async def test_redis_client():
    redis_client: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)

    try:
        yield redis_client
    finally:
        await redis_client.flushdb()
        await redis_client.aclose()


async def _no_limit():
    return None


@pytest_asyncio.fixture
async def async_client(
    request: pytest.FixtureRequest,
    session_maker: async_sessionmaker[AsyncSession],
    test_redis_client: Redis,
):
    async def get_test_session():
        session = session_maker()
        yield session
        await session.close()

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_redis_client] = lambda: test_redis_client

    rate_limited: bool = request.node.get_closest_marker("rate_limited") is not None

    if not rate_limited:
        app.dependency_overrides[write_limiter.dependency] = _no_limit
        app.dependency_overrides[read_limiter.dependency] = _no_limit

    # ASGITransport does not send lifespan events, so run the app's lifespan
    # explicitly to populate app.state (limiters, redis) like a real server.
    async with app.router.lifespan_context(app):
        app_redis: Redis = app.state.redis

        if rate_limited:
            # count requests in the test redis db, starting from empty buckets
            app.state.redis = test_redis_client
            app.state.limiters = {}

        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test/api/v1"
        ) as client:
            yield client

        app.state.redis = app_redis

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def otp_code():
    """Fix the generated code so tests can submit what would have been emailed"""
    with patch.object(OtpService, "_generate_code", return_value=OTP_CODE):
        yield OTP_CODE


@pytest_asyncio.fixture
async def register(async_client: AsyncClient) -> Response:
    return await async_client.post("/auth/register", json=SIGN_UP_PAYLOAD)


@pytest_asyncio.fixture
async def verify(async_client: AsyncClient, register: Response) -> Response:
    return await async_client.post(
        "/auth/verify", json={"email": SIGN_UP_PAYLOAD["email"], "otp_code": OTP_CODE}
    )


@pytest_asyncio.fixture
async def login(async_client: AsyncClient, verify: Response) -> Response:
    login_payload: dict = {
        "email": SIGN_UP_PAYLOAD["email"],
        "password": SIGN_UP_PAYLOAD["password"],
    }
    return await async_client.post("/auth/login", json=login_payload)


@pytest_asyncio.fixture
async def auth_headers(login: Response) -> dict:
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
