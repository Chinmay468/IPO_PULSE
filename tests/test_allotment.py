import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_linkintime_companies(client: AsyncClient):
    res = await client.get("/api/v1/allotment/linkintime/companies")
    assert res.status_code == 200
    companies = res.json()
    assert isinstance(companies, list)
    assert len(companies) > 0
    assert "company_id" in companies[0]
    assert "company_name" in companies[0]


@pytest.mark.asyncio
async def test_check_allotment_status(client: AsyncClient):
    # Query with test PAN
    req_payload = {
        "company_id": "1001",
        "query_type": "PAN",
        "query_value": "ABCDE1234A"
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 200
    data = res.json()
    # Live query without mock will fail cleanly or return status
    if data["success"]:
        assert data["status"] in ["ALLOTTED", "NOT_ALLOTTED", "NOT_FOUND"]
    else:
        assert data["status"] == "ERROR"
        assert data["message"] == "Registrar unavailable, try again later"


@pytest.mark.asyncio
async def test_check_allotment_registrar_unavailable(client: AsyncClient, monkeypatch):
    import httpx

    class MockFailingClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            raise httpx.ConnectTimeout("Registrar timeout")
        async def get(self, *args, **kwargs):
            raise httpx.ConnectTimeout("Registrar timeout")

    monkeypatch.setattr("app.services.registrar_proxy.httpx.AsyncClient", MockFailingClient)

    req_payload = {
        "company_id": "1001",
        "query_type": "PAN",
        "query_value": "ABCDE1234A"
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert data["status"] == "ERROR"
    assert data["message"] == "Registrar unavailable, try again later"


@pytest.mark.asyncio
async def test_check_allotment_validation(client: AsyncClient):
    # Query with invalid empty query_value
    req_payload = {
        "company_id": "1001",
        "query_type": "PAN",
        "query_value": "  "
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 422
