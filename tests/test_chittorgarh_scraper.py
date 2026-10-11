import os
import pytest
import httpx
from unittest.mock import AsyncMock, patch
from pathlib import Path

from app.models.ipo import IPO, IPOType, IPOStatus, IPOScore
from app.services.chittorgarh_scraper import (
    ChittorgarhClient,
    StructureChangeDetector,
    ChittorgarhRateLimitException,
    ChittorgarhStructureChangeException,
    parse_dashboard_list,
    parse_dashboard_reviews,
    parse_ipo_detail,
    normalize_company_name,
)
from app.services.scoring_service import ScoringService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mainboard_dashboard_html():
    file_path = FIXTURES_DIR / "chittorgarh_mainboard_dashboard.html"
    return file_path.read_text(encoding="utf-8")


@pytest.fixture
def sme_dashboard_html():
    file_path = FIXTURES_DIR / "chittorgarh_sme_dashboard.html"
    return file_path.read_text(encoding="utf-8")


@pytest.fixture
def ipo_detail_html():
    file_path = FIXTURES_DIR / "chittorgarh_ipo_detail.html"
    return file_path.read_text(encoding="utf-8")


@pytest.fixture
def upcoming_drhp_html():
    file_path = FIXTURES_DIR / "chittorgarh_upcoming_drhp.html"
    return file_path.read_text(encoding="utf-8")


@pytest.fixture
def perf_tracker_html():
    file_path = FIXTURES_DIR / "chittorgarh_perf_tracker.html"
    return file_path.read_text(encoding="utf-8")


# ---------------- 1. Parser Tests with Saved Fixtures ----------------
def test_parse_dashboard_list_mainboard(mainboard_dashboard_html):
    items = parse_dashboard_list(mainboard_dashboard_html, ipo_type=IPOType.MAINBOARD)
    assert len(items) > 0
    first = items[0]
    assert "company_name" in first
    assert first["company_name"] != ""
    assert first["ipo_type"] == IPOType.MAINBOARD
    assert "source_url" in first
    assert "source_id" in first
    assert first["source_id"] is not None


def test_parse_dashboard_list_sme(sme_dashboard_html):
    items = parse_dashboard_list(sme_dashboard_html, ipo_type=IPOType.SME)
    assert len(items) > 0
    first = items[0]
    assert first["ipo_type"] == IPOType.SME
    assert first["source_url"].startswith("http")


def test_parse_dashboard_reviews(mainboard_dashboard_html):
    reviews = parse_dashboard_reviews(mainboard_dashboard_html)
    assert isinstance(reviews, dict)
    assert len(reviews) > 0
    # Every review entry should have numeric broker vote counters
    for name, counts in reviews.items():
        assert "apply" in counts
        assert "avoid" in counts
        assert isinstance(counts["apply"], int)
        assert isinstance(counts["avoid"], int)


def test_parse_other_dashboards(upcoming_drhp_html, perf_tracker_html):
    drhp_items = parse_dashboard_list(upcoming_drhp_html, ipo_type=IPOType.MAINBOARD)
    perf_items = parse_dashboard_list(perf_tracker_html, ipo_type=IPOType.MAINBOARD)
    assert isinstance(drhp_items, list)
    assert isinstance(perf_items, list)


def test_parse_ipo_detail_fixture(ipo_detail_html):
    url = "https://www.chittorgarh.com/ipo/vishal-nirmiti-ipo/2357/"
    detail = parse_ipo_detail(ipo_detail_html, source_url=url, source_id=2357)

    assert "vishal" in detail["company_name"].lower()
    assert detail["source_id"] == 2357
    assert detail["source_url"] == url
    assert detail["price_band_high"] is not None
    assert detail["lot_size"] is not None
    assert detail["issue_size_crores"] is not None
    assert detail["pe_ratio"] is not None
    assert detail["ronw"] is not None
    assert detail["promoter_holding_pre"] is not None
    assert detail["promoter_holding_post"] is not None

    # Data quality tracker assertions
    dq = detail["data_quality"]
    assert "missing_fields" in dq
    assert "completeness_pct" in dq
    assert dq["fields_present"] > 5
    assert dq["status"] in ["complete", "incomplete"]


# ---------------- 2. Missing-Field & NULL Handling ----------------
def test_missing_field_case_returns_null_never_zero():
    sparse_html = """
    <html>
    <body>
        <h1>Sparse Incomplete IPO</h1>
        <table>
            <tr><td>Lot Size</td><td>1000 Shares</td></tr>
            <tr><td>Face Value</td><td>Rs 10</td></tr>
        </table>
    </body>
    </html>
    """
    parsed = parse_ipo_detail(sparse_html, source_url="https://www.chittorgarh.com/ipo/sparse/999/", source_id=999)

    # Missing metrics must be strictly None, NEVER defaulted to 0
    assert parsed["pe_ratio"] is None
    assert parsed["ronw"] is None
    assert parsed["eps"] is None
    assert parsed["issue_size_crores"] is None
    assert parsed["revenue_growth_yoy"] is None
    assert parsed["pat_growth_yoy"] is None

    dq = parsed["data_quality"]
    assert "pe_ratio" in dq["missing_fields"]
    assert "ronw" in dq["missing_fields"]
    assert "eps" in dq["missing_fields"]
    assert dq["status"] == "incomplete"
    assert dq["completeness_pct"] < 50.0

    # Test scoring engine penalizes confidence when key metrics are NULL
    sparse_ipo = IPO(
        symbol="SPARSE",
        company_name="Sparse Incomplete IPO",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        pe_ratio=None,
        ronw=None,
        issue_size_crores=None,
        lot_size=1000,
        data_quality=dq
    )
    score_res = ScoringService.calculate_score(sparse_ipo)
    assert score_res["confidence_pct"] < 100.0
    assert score_res["data_incomplete"] is True
    assert score_res["rationale"]["data_incomplete"] is True
    assert "P/E ratio missing" in " ".join(score_res["rationale"]["risk_factors"])


# ---------------- 3. Robots.txt and Rate Limit Enforcement ----------------
@pytest.mark.asyncio
async def test_robots_txt_disallow_enforcement():
    client = ChittorgarhClient()
    client._robots_loaded = True
    # Test checking disallowed path
    assert not client.is_url_allowed("https://www.chittorgarh.com/ipo/ipo_discussions.asp")
    assert client.is_url_allowed("https://www.chittorgarh.com/ipo/sample-ipo/123/")

    with pytest.raises(ValueError, match="prohibited by robots.txt"):
        await client.fetch("https://www.chittorgarh.com/ipo/ipo_discussions.asp")


@pytest.mark.asyncio
async def test_scraper_aborts_on_http_403_and_429():
    client = ChittorgarhClient()
    client._robots_loaded = True

    # Test 403 Forbidden triggers ChittorgarhRateLimitException
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = httpx.Response(status_code=403, request=httpx.Request("GET", "https://www.chittorgarh.com/test"))
        mock_get.return_value = mock_resp

        with pytest.raises(ChittorgarhRateLimitException):
            await client.fetch("https://www.chittorgarh.com/ipo/test-403/100/")

    # Test 429 Too Many Requests triggers ChittorgarhRateLimitException
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = httpx.Response(status_code=429, request=httpx.Request("GET", "https://www.chittorgarh.com/test"))
        mock_get.return_value = mock_resp

        with pytest.raises(ChittorgarhRateLimitException):
            await client.fetch("https://www.chittorgarh.com/ipo/test-429/101/")


# ---------------- 4. Structure-Change Detection ----------------
@pytest.mark.asyncio
async def test_structure_change_detector_alerts_and_halts():
    detector = StructureChangeDetector(max_consecutive_failures=3)

    with patch("app.services.telegram_service.TelegramService.send_message", new_callable=AsyncMock) as mock_tg:
        # Failure 1: consecutive 1 -> no alert
        await detector.record_result("ipo_detail", fields_found=0, url="http://url1")
        assert detector.consecutive_failures == 1
        mock_tg.assert_not_called()

        # Failure 2: consecutive 2 -> no alert
        await detector.record_result("ipo_detail", fields_found=0, url="http://url2")
        assert detector.consecutive_failures == 2
        mock_tg.assert_not_called()

        # Failure 3: triggers alert and raises exception
        with pytest.raises(ChittorgarhStructureChangeException):
            await detector.record_result("ipo_detail", fields_found=0, url="http://url3")

        assert detector.consecutive_failures == 3
        mock_tg.assert_called_once()
        alert_msg = mock_tg.call_args[0][0]
        assert "Scraper Structure Change Detected" in alert_msg


@pytest.mark.asyncio
async def test_structure_change_detector_resets_on_success():
    detector = StructureChangeDetector(max_consecutive_failures=3)

    # 2 consecutive failures
    await detector.record_result("ipo_detail", fields_found=0, url="http://url1")
    await detector.record_result("ipo_detail", fields_found=0, url="http://url2")
    assert detector.consecutive_failures == 2

    # Success page resets counter to 0
    await detector.record_result("ipo_detail", fields_found=10, url="http://url3")
    assert detector.consecutive_failures == 0
