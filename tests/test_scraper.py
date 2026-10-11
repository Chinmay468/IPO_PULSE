import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_scraper_status(client: AsyncClient):
    res = await client.get("/api/v1/scraper/status")
    assert res.status_code == 200
    data = res.json()
    assert "scraper_enabled" in data
    assert "interval_minutes" in data
    assert "is_discovery_stale" in data


@pytest.mark.asyncio
async def test_scraper_seed_and_sync(auth_client: AsyncClient, monkeypatch):
    client = auth_client
    # Gated: without ALLOW_SEED=1, returns 403 Forbidden
    res_forbidden = await client.post("/api/v1/scraper/seed")
    assert res_forbidden.status_code == 403

    # Enabled: with ALLOW_SEED=1, succeeds
    monkeypatch.setenv("ALLOW_SEED", "1")
    res_seed = await client.post("/api/v1/scraper/seed")
    assert res_seed.status_code == 200
    assert "Successfully seeded" in res_seed.json()["message"]

    # Verify seeded IPOs exist when requested via include_seed=true
    res_ipos = await client.get("/api/v1/ipos?include_seed=true")
    assert res_ipos.status_code == 200
    items = res_ipos.json()["items"]
    assert len(items) > 0

    # Default /api/v1/ipos excludes seed rows
    res_default = await client.get("/api/v1/ipos")
    assert res_default.status_code == 200
    for item in res_default.json()["items"]:
        assert item.get("is_seed") is False or item.get("is_seed") is None

    # Manual sync trigger
    res_sync = await client.post("/api/v1/scraper/sync")
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data["status"] == "success"
