import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_scraper_status(auth_client: AsyncClient):
    client = auth_client
    res = await client.get("/api/v1/scraper/status")
    assert res.status_code == 200
    data = res.json()
    assert "scraper_enabled" in data
    assert "interval_minutes" in data


@pytest.mark.asyncio
async def test_scraper_seed_and_sync(auth_client: AsyncClient):
    client = auth_client
    # Seed data
    res_seed = await client.post("/api/v1/scraper/seed")
    assert res_seed.status_code == 200
    assert "Successfully seeded" in res_seed.json()["message"]

    # Verify seeded IPOs exist
    res_ipos = await client.get("/api/v1/ipos")
    assert res_ipos.status_code == 200
    items = res_ipos.json()["items"]
    assert len(items) > 0

    # Manual sync trigger
    res_sync = await client.post("/api/v1/scraper/sync")
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data["status"] == "success"
