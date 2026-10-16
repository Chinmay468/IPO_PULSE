import pytest
import logging
from datetime import date, timedelta
from httpx import AsyncClient
from unittest.mock import patch, MagicMock

from app.models.ipo import IPO, IPOStatus, IPOType
from app.core.registrars import CanonicalRegistrar, DEFAULT_REGISTRAR_URLS
from app.schemas.ipo import RegistrarCompanyItem


@pytest.mark.asyncio
async def test_get_linkintime_companies(client: AsyncClient, monkeypatch):
    # Mock Link Intime returning active issues
    mock_comps = [
        RegistrarCompanyItem(company_id="11959", company_name="Runwal Enterprise Limited - IPO"),
        RegistrarCompanyItem(company_id="11960", company_name="Acevector Limited - IPO")
    ]
    monkeypatch.setattr(
        "app.services.registrar_proxy.RegistrarProxyService.get_linkintime_companies",
        lambda: [mock_comps[0], mock_comps[1]] if False else _async_return(mock_comps)
    )

    res = await client.get("/api/v1/allotment/linkintime/companies")
    assert res.status_code == 200
    companies = res.json()
    assert isinstance(companies, list)
    assert len(companies) == 2
    assert companies[0]["company_id"] == "11959"


async def _async_return(val):
    return val


@pytest.mark.asyncio
async def test_get_allotment_ipos_empty_database(client: AsyncClient):
    """If database has no IPOs, return empty list with clear message."""
    res = await client.get("/api/v1/allotment/ipos")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["ipos"] == []
    assert data["message"] == "No IPO data available."


@pytest.mark.asyncio
async def test_get_allotment_ipos_search_filter_and_inline_flags(client: AsyncClient, db_session):
    today = date.today()

    ipo_link = IPO(
        symbol="LINKIPO",
        company_name="Link Intime Mainboard Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        open_date=today - timedelta(days=1),
        close_date=today + timedelta(days=2),
        allotment_date=today + timedelta(days=4),
        registrar_name=CanonicalRegistrar.LINKINTIME,
        registrar_code="11959",
        issue_price=150.0,
    )
    ipo_kfin = IPO(
        symbol="KFINIPO",
        company_name="KFintech Super Tech Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        open_date=today + timedelta(days=5),
        close_date=today + timedelta(days=8),
        allotment_date=today + timedelta(days=10),
        registrar_name=CanonicalRegistrar.KFINTECH,
        issue_price=200.0,
    )
    ipo_bigshare = IPO(
        symbol="BIGIPO",
        company_name="Bigshare Retail SME Ltd",
        ipo_type=IPOType.SME,
        status=IPOStatus.CLOSED,
        open_date=today - timedelta(days=10),
        close_date=today - timedelta(days=7),
        allotment_date=today - timedelta(days=5),
        registrar_name=CanonicalRegistrar.BIGSHARE,
        issue_price=50.0,
    )

    db_session.add_all([ipo_link, ipo_kfin, ipo_bigshare])
    await db_session.commit()

    # 1. Fetch all
    res = await client.get("/api/v1/allotment/ipos")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3

    items_by_symbol = {item["symbol"]: item for item in data["ipos"]}

    # Supported inline flag: ONLY True for Link Intime
    assert items_by_symbol["LINKIPO"]["supported_inline"] is True
    assert items_by_symbol["LINKIPO"]["registrar_name"] == "LINKINTIME"
    assert items_by_symbol["LINKIPO"]["registrar_code"] == "11959"

    assert items_by_symbol["KFINIPO"]["supported_inline"] is False
    assert items_by_symbol["KFINIPO"]["registrar_name"] == "KFINTECH"
    assert items_by_symbol["KFINIPO"]["registrar_allotment_url"] == DEFAULT_REGISTRAR_URLS[CanonicalRegistrar.KFINTECH]

    assert items_by_symbol["BIGIPO"]["supported_inline"] is False
    assert items_by_symbol["BIGIPO"]["registrar_name"] == "BIGSHARE"
    assert items_by_symbol["BIGIPO"]["registrar_allotment_url"] == DEFAULT_REGISTRAR_URLS[CanonicalRegistrar.BIGSHARE]

    # 2. Search query by company name
    res_q = await client.get("/api/v1/allotment/ipos?q=super+tech")
    assert res_q.status_code == 200
    data_q = res_q.json()
    assert data_q["total"] == 1
    assert data_q["ipos"][0]["symbol"] == "KFINIPO"

    # 3. Search query by symbol
    res_sym = await client.get("/api/v1/allotment/ipos?q=bigipo")
    assert res_sym.status_code == 200
    data_sym = res_sym.json()
    assert data_sym["total"] == 1
    assert data_sym["ipos"][0]["symbol"] == "BIGIPO"

    # 4. Status filter
    res_st = await client.get("/api/v1/allotment/ipos?status=LIVE")
    assert res_st.status_code == 200
    data_st = res_st.json()
    assert data_st["total"] == 1
    assert data_st["ipos"][0]["symbol"] == "LINKIPO"

    # 5. Search with no matches
    res_none = await client.get("/api/v1/allotment/ipos?q=nonexistentxyz")
    assert res_none.status_code == 200
    data_none = res_none.json()
    assert data_none["total"] == 0
    assert data_none["ipos"] == []
    assert "No IPOs found in the database matching your search." in data_none["message"]


@pytest.mark.asyncio
async def test_check_allotment_validation(client: AsyncClient):
    req_payload = {
        "company_id": "11959",
        "query_type": "PAN",
        "query_value": "  "
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_check_allotment_failures_specific_messages_never_fabricated(client: AsyncClient, monkeypatch):
    """
    Requirement 5: If registrar is unavailable or IPO is no longer listed there,
    show specific messages ("Registrar unavailable" or "No longer available on the registrar").
    Never show a fabricated result (e.g. shares_allotted must be 0, success=False).
    """
    import httpx

    # Scenario A: Registrar unavailable (network error / timeout)
    class MockTimeoutClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            raise httpx.ConnectTimeout("Connection to registrar timed out")
        async def get(self, *args, **kwargs):
            raise httpx.ConnectTimeout("Connection to registrar timed out")

    monkeypatch.setattr("app.services.registrar_proxy.httpx.AsyncClient", MockTimeoutClient)

    req_payload = {
        "company_id": "11959",
        "query_type": "PAN",
        "query_value": "ABCDE1234F"
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert data["status"] == "ERROR"
    assert data["message"] == "Registrar unavailable"
    # Never fabricated:
    assert data["shares_applied"] == 0
    assert data["shares_allotted"] == 0
    assert data["refund_amount"] == 0.0

    # Scenario B: IPO no longer listed on registrar
    # Mock registrar returning an active company list that DOES NOT include requested company_id
    mock_active_companies = [
        RegistrarCompanyItem(company_id="99999", company_name="Other Active IPO Ltd")
    ]
    monkeypatch.setattr(
        "app.services.registrar_proxy.RegistrarProxyService.get_linkintime_companies",
        lambda: _async_return(mock_active_companies)
    )

    req_payload_delisted = {
        "company_id": "11959",  # Not in active list
        "query_type": "PAN",
        "query_value": "ABCDE1234F"
    }
    res_delisted = await client.post("/api/v1/allotment/linkintime/check", json=req_payload_delisted)
    assert res_delisted.status_code == 200
    data_delisted = res_delisted.json()
    assert data_delisted["success"] is False
    assert data_delisted["status"] == "ERROR"
    assert data_delisted["message"] == "No longer available on the registrar"
    # Never fabricated:
    assert data_delisted["shares_applied"] == 0
    assert data_delisted["shares_allotted"] == 0


@pytest.mark.asyncio
async def test_check_allotment_success_allotted_and_masked_privacy(client: AsyncClient, monkeypatch):
    """
    Test live allotment success: shares allotted, and sensitive identifier is masked in response.
    Never return raw PAN.
    """
    mock_active_companies = [
        RegistrarCompanyItem(company_id="11959", company_name="Runwal Enterprise Limited - IPO")
    ]
    monkeypatch.setattr(
        "app.services.registrar_proxy.RegistrarProxyService.get_linkintime_companies",
        lambda: _async_return(mock_active_companies)
    )

    sample_xml = """<NewDataSet>
        <Table>
            <company_id>11959</company_id>
            <SEC>Runwal Enterprise Limited - IPO</SEC>
            <NAME1>Rahul Sharma</NAME1>
            <ALLOT>75</ALLOT>
            <APPL>75</APPL>
            <RFNDAMT>0</RFNDAMT>
        </Table>
    </NewDataSet>"""

    class MockSuccessClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, *args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "generateToken" in str(url):
                mock_resp.json.return_value = {"d": "test-session-token"}
            elif "SearchOnPan" in str(url):
                mock_resp.json.return_value = {"d": sample_xml}
            return mock_resp
        async def get(self, *args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

    monkeypatch.setattr("app.services.registrar_proxy.httpx.AsyncClient", MockSuccessClient)

    raw_pan = "ABCDE1234F"
    req_payload = {
        "company_id": "11959",
        "query_type": "PAN",
        "query_value": raw_pan
    }
    res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert data["status"] == "ALLOTTED"
    assert data["shares_allotted"] == 75
    assert data["shares_applied"] == 75

    # CRITICAL: PAN MUST BE MASKED (e.g. AB****4F). Raw PAN must NOT be returned!
    assert data["pan"] == "AB****4F"
    assert raw_pan not in str(data)


@pytest.mark.asyncio
async def test_no_pan_in_logs(client: AsyncClient, caplog, monkeypatch):
    """
    CRITICAL REQUIREMENT:
    Never log, store, or return raw PAN, application numbers, or DP/Client IDs.
    Ensure that masked identifier is logged, and raw PAN NEVER appears in logs.
    """
    mock_active_companies = [
        RegistrarCompanyItem(company_id="11959", company_name="Runwal Enterprise Limited - IPO")
    ]
    monkeypatch.setattr(
        "app.services.registrar_proxy.RegistrarProxyService.get_linkintime_companies",
        lambda: _async_return(mock_active_companies)
    )

    class MockFailingClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            return mock_resp

    monkeypatch.setattr("app.services.registrar_proxy.httpx.AsyncClient", MockFailingClient)

    sensitive_pan = "XYZPA9876Q"
    req_payload = {
        "company_id": "11959",
        "query_type": "PAN",
        "query_value": sensitive_pan
    }

    with caplog.at_level(logging.INFO):
        res = await client.post("/api/v1/allotment/linkintime/check", json=req_payload)
        assert res.status_code == 200

    # Raw sensitive PAN must NEVER appear anywhere in the logs
    assert sensitive_pan not in caplog.text

    # Masked identifier MUST appear
    assert "XY****6Q" in caplog.text


@pytest.mark.asyncio
async def test_linkintime_daily_mapping_and_unmatched_reporting(client: AsyncClient, db_session, monkeypatch):
    """
    Requirement 6: Refresh Link Intime company list daily and map each Link Intime
    company to IPOs by normalized name. Report unmatched ones.
    """
    from app.services.scheduler import scheduled_linkintime_company_sync

    today = date.today()
    ipo_runwal = IPO(
        symbol="RUNWAL",
        company_name="Runwal Enterprise Limited",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        open_date=today,
        close_date=today + timedelta(days=2),
        issue_price=100.0,
    )
    db_session.add(ipo_runwal)
    await db_session.commit()

    # Link Intime returns 2 companies: Runwal (matches DB) and Unmatched Co (no match)
    mock_link_comps = [
        RegistrarCompanyItem(company_id="11959", company_name="Runwal Enterprise Limited - IPO"),
        RegistrarCompanyItem(company_id="88888", company_name="Unmatched Mystery Enterprises Limited - SME IPO")
    ]
    monkeypatch.setattr(
        "app.services.registrar_proxy.RegistrarProxyService.get_linkintime_companies",
        lambda: _async_return(mock_link_comps)
    )

    class DummyAsyncSessionLocal:
        def __init__(self, session):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=DummyAsyncSessionLocal(db_session)):
        sync_result = await scheduled_linkintime_company_sync()

    assert sync_result["total_companies"] == 2
    assert sync_result["matched"] == 1
    assert len(sync_result["unmatched"]) == 1
    assert sync_result["unmatched"][0]["company_id"] == "88888"

    await db_session.refresh(ipo_runwal)
    assert ipo_runwal.registrar_name == CanonicalRegistrar.LINKINTIME
    assert ipo_runwal.registrar_code == "11959"
    assert ipo_runwal.registrar_allotment_url == DEFAULT_REGISTRAR_URLS[CanonicalRegistrar.LINKINTIME]

    # Verify /api/v1/allotment/linkintime/unmatched endpoint reports the unmatched companies
    unmatched_res = await client.get("/api/v1/allotment/linkintime/unmatched")
    assert unmatched_res.status_code == 200
    unmatched_data = unmatched_res.json()
    assert unmatched_data["count"] == 1
    assert unmatched_data["unmatched"][0]["company_id"] == "88888"
