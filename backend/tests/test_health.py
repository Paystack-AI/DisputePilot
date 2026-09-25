import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(async_client: AsyncClient):
    response = await async_client.get("http://test/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
