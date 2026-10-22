from collections.abc import AsyncGenerator

from redis import ConnectionPool as SyncConnectionPool
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError
from redis.retry import Retry
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

SETTINGS = get_settings()

async_engine: AsyncEngine = create_async_engine(
    url=SETTINGS.ASYNC_DB_URL,
    connect_args={"server_settings": {"timezone": "utc"}, "statement_cache_size": 0},
    pool_size=10,
    max_overflow=5,
    pool_timeout=10.0,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    class_=AsyncSession,
    expire_on_commit=False,
)

sync_engine: Engine = create_engine(
    url=SETTINGS.SYNC_DB_URL,
    pool_size=10,
    pool_timeout=10.0,
    pool_pre_ping=True,
    max_overflow=5,
    connect_args={"options": "-c timezone=utc"},
)

sync_session = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)

redis_pool = ConnectionPool.from_url(
    SETTINGS.REDIS_URL,
    decode_responses=True,
    max_connections=SETTINGS.REDIS_MAX_CONNECTIONS,
    # redis-py 8 times a reply out after 5s by default; the blocking stream reads (the
    # event stream's heartbeat wait, the ai result consumer) wait longer than that
    socket_timeout=max(SETTINGS.EVENT_HEARTBEAT_SECONDS, SETTINGS.AI_RESULT_BLOCK_MS / 1000) + 5,
    retry=Retry(ExponentialBackoff(cap=1.0, base=0.1), retries=5),
    retry_on_error=[ConnectionError, TimeoutError],
    retry_on_timeout=True,
)

"""
A redis client with:
- a connection pool that maintains a set of live connections
- retry mechanism with exponential backoff and jitters for randomness
"""

redis_client: Redis = Redis(connection_pool=redis_pool)

# for celery tasks, which run without an event loop; connects on first use
sync_redis_client: SyncRedis = SyncRedis(
    connection_pool=SyncConnectionPool.from_url(
        SETTINGS.REDIS_URL,
        decode_responses=True,
        max_connections=10,
        socket_connect_timeout=3,
        socket_timeout=5,
    )
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
