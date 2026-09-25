import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def async_client():
    # ASGITransport does not send lifespan events, so run the app's lifespan
    # explicitly to populate app.state (limiters, redis) like a real server.
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test/api/v1"
        ) as client:
            yield client

    app.dependency_overrides.clear()
