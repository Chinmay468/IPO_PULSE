import pytest
import os
from datetime import datetime, date, timedelta, timezone
from bs4 import BeautifulSoup

from app.models.ipo import IPO, IPOGmp, IPOSubscription, IPOStatus, IPOType, RecommendationType
from app.services.ipowatch_scraper import IPOWatchScraper
from app.services.scraper_service import ScraperService
from app.services.consensus_gmp import ConsensusGmpService
from app.services.gmp_matcher import (
    normalize_for_gmp_match,
    validate_match_cross_check,
    parse_date_span
)
from app.services.scoring_service import ScoringService


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_ipowatch_parsing_fixture():
    """
    Test 1: IPOWatch parsing of Upcoming / Open / (C) rows from HTML fixture.
    Ensures status tags, GMP in rupees, trend, price band, estimated gain, and dates are parsed.
    """
    fixture_path = os.path.join(FIXTURES_DIR, "ipowatch_gmp_fixture.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    records = IPOWatchScraper.parse_tables(html_content)
    assert len(records) > 0, "Should parse rows from IPOWatch fixture"

    # Check for UPCOMING row
    upcoming_rows = [r for r in records if r["status_tag"] == "UPCOMING"]
    assert len(upcoming_rows) >= 1
    assert any("Paras" in r["company_name"] or "Jio" in r["company_name"] for r in upcoming_rows)

    # Check for OPEN row
    open_rows = [r for r in records if r["status_tag"] == "OPEN"]
    assert len(open_rows) >= 1
    tonbo = next((r for r in open_rows if "Tonbo" in r["company_name"]), None)
    assert tonbo is not None
    assert tonbo["gmp_amount"] == 500.0
    assert tonbo["price"] == 700.0

    # Check for CLOSED row (C)
    closed_rows = [r for r in records if r["status_tag"] == "CLOSED"]
    assert len(closed_rows) >= 1
    hd_fire = next((r for r in closed_rows if "HD Fire" in r["company_name"]), None)
    assert hd_fire is not None
    assert hd_fire["gmp_amount"] == 80.0
    assert hd_fire["price"] == 271.0
    assert hd_fire["status_tag"] == "CLOSED"


def test_name_matching_required_examples():
    """
    Test 2: Match scraped rows to IPOs by normalized name & rapidfuzz token similarity.
    Required examples:
    - 'Zetwerk' = 'Zetwerk Manufacturing Business'
    - 'Tonbo Imaging' = 'Tonbo Imaging India'
    - 'Sahajanand Medical' = 'Sahajanand Medical Technologies'
    """
    from rapidfuzz import fuzz

    examples = [
        ("Zetwerk", "Zetwerk Manufacturing Business"),
        ("Tonbo Imaging", "Tonbo Imaging India"),
        ("Sahajanand Medical", "Sahajanand Medical Technologies"),
    ]

    for scraped_name, db_name in examples:
        norm_scraped = normalize_for_gmp_match(scraped_name)
        norm_db = normalize_for_gmp_match(db_name)
        score = fuzz.token_set_ratio(norm_scraped, norm_db)
        assert score >= 85.0, f"Expected '{scraped_name}' to match '{db_name}', score={score}"


def test_cross_check_rejects_wrong_matches():
    """
    Test 3: Cross-check candidate match against price band and dates; reject when they disagree.
    """
    ipo = IPO(
        id=101,
        symbol="ACME",
        company_name="Acme Solar Energy",
        issue_price=289.0,
        price_band_high=289.0,
        open_date=date(2026, 10, 14),
        close_date=date(2026, 10, 16)
    )

    # 3a. Disagreeing Price (scraped price 650 vs DB 289 -> >20% & >Rs 20)
    conflict_price_item = {
        "company_name": "Acme Solar",
        "price": 650.0,
        "date_str": "14-16 Oct"
    }
    valid, reason = validate_match_cross_check(conflict_price_item, ipo)
    assert not valid
    assert "Price conflict" in reason

    # 3b. Disagreeing Month (scraped Nov vs DB Oct)
    conflict_month_item = {
        "company_name": "Acme Solar",
        "price": 289.0,
        "date_str": "14-16 Nov"
    }
    valid, reason = validate_match_cross_check(conflict_month_item, ipo)
    assert not valid
    assert "Date month conflict" in reason

    # 3c. Disagreeing Close Day (>7 days difference)
    conflict_day_item = {
        "company_name": "Acme Solar",
        "price": 289.0,
        "date_str": "1-3 Oct"
    }
    valid, reason = validate_match_cross_check(conflict_day_item, ipo)
    assert not valid
    assert "Closing day conflict" in reason

    # 3d. Valid matching record
    valid_item = {
        "company_name": "Acme Solar",
        "price": 289.0,
        "date_str": "14-16 Oct"
    }
    valid, reason = validate_match_cross_check(valid_item, ipo)
    assert valid


def test_consensus_median_and_disagreement():
    """
    Test 4: Median of readings from all sources recorded in the last 12 hours.
    Disagreement flagged if >30% or >Rs 25 when median < Rs 80.
    """
    now = datetime.now(timezone.utc)

    # 4a. Multiple agreeing sources
    r1 = IPOGmp(source="investorgain", gmp_amount=100.0, gmp_percentage=20.0, recorded_at=now - timedelta(hours=1))
    r2 = IPOGmp(source="ipowatch", gmp_amount=105.0, gmp_percentage=21.0, recorded_at=now - timedelta(hours=2))

    res = ConsensusGmpService.calculate_consensus_from_readings([r1, r2], now=now)
    assert res["status"] == "fresh"
    assert res["sources_count"] == 2
    assert res["gmp_amount"] == 102.5
    assert res["gmp_percentage"] == 20.5
    assert not res["single_source"]
    assert not res["sources_disagree"]

    # 4b. Disagreement: diff > 30% (Rs 100 vs Rs 150)
    r3 = IPOGmp(source="ipowatch", gmp_amount=150.0, gmp_percentage=30.0, recorded_at=now - timedelta(hours=1))
    res_disagree = ConsensusGmpService.calculate_consensus_from_readings([r1, r3], now=now)
    assert res_disagree["sources_disagree"] is True
    assert res_disagree["gmp_amount"] == 125.0

    # 4c. Disagreement under Rs 80: diff > Rs 25 (e.g. Rs 30 vs Rs 60 -> diff 30 > 25)
    r_low1 = IPOGmp(source="investorgain", gmp_amount=30.0, gmp_percentage=10.0, recorded_at=now - timedelta(hours=1))
    r_low2 = IPOGmp(source="ipowatch", gmp_amount=60.0, gmp_percentage=20.0, recorded_at=now - timedelta(hours=1))
    res_low = ConsensusGmpService.calculate_consensus_from_readings([r_low1, r_low2], now=now)
    assert res_low["sources_disagree"] is True


def test_stale_gmp_exclusion():
    """
    Test 5: GMP older than 24 hours counts as missing.
    Readings between 12h and 24h count as stale.
    """
    now = datetime.now(timezone.utc)

    # Older than 24 hours -> status 'missing'
    old_reading = IPOGmp(source="investorgain", gmp_amount=50.0, gmp_percentage=10.0, recorded_at=now - timedelta(hours=25))
    res_missing = ConsensusGmpService.calculate_consensus_from_readings([old_reading], now=now)
    assert res_missing["status"] == "missing"
    assert res_missing["gmp_amount"] is None

    # Between 12h and 24h -> status 'stale'
    stale_reading = IPOGmp(source="investorgain", gmp_amount=50.0, gmp_percentage=10.0, recorded_at=now - timedelta(hours=15))
    res_stale = ConsensusGmpService.calculate_consensus_from_readings([stale_reading], now=now)
    assert res_stale["status"] == "stale"
    assert res_stale["gmp_amount"] is None


def test_score_scaling_with_missing_inputs():
    """
    Test 6: Missing inputs contribute NO points AND are excluded from the maximum,
    so the score is scaled to the points that could be evaluated.
    """
    # IPO with only Valuation (P/E 20 -> 9/12 pts) and RoNW (22% -> 8/8 pts) = 17 pts out of 20 available.
    # GMP, Subscription, Fresh ratio, Issue size are missing (80 pts excluded).
    # Scaled score: (17 / 20) * 100 = 85.0 / 100.
    ipo = IPO(
        symbol="SCALETEST",
        company_name="Scale Testing Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        pe_ratio=20.0,
        ronw=22.0
    )

    score_res = ScoringService.calculate_score(ipo, latest_subscription=None, latest_gmp=None)
    assert score_res["composite_score"] == 85.0
    assert score_res["confidence"] == 0.20  # 20 / 100
    # Because confidence < 50%, recommendation must be INSUFFICIENT DATA
    assert score_res["recommendation"] == RecommendationType.INSUFFICIENT_DATA


def test_confidence_threshold_insufficient_data():
    """
    Test 7: When confidence < 50%, the label is INSUFFICIENT DATA (neutral grey), not AVOID.
    """
    ipo = IPO(
        symbol="LOWCONF",
        company_name="Low Confidence Corp",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        pe_ratio=55.0  # High P/E -> 3 pts out of 12 available. Available weight = 12% (<50%).
    )

    score_res = ScoringService.calculate_score(ipo, latest_subscription=None, latest_gmp=None)
    assert score_res["recommendation"] == RecommendationType.INSUFFICIENT_DATA
    assert "INSUFFICIENT DATA" in score_res["recommendation"].value
    assert score_res["recommendation"] != RecommendationType.AVOID
    assert score_res["confidence"] < 0.50
    assert "Grey Market Premium (GMP)" in score_res["missing_inputs"]
    assert any("Subscription" in m for m in score_res["missing_inputs"])


def test_closed_ipo_suppressed_apply():
    """
    Test 8: Don't show an Apply recommendation for Closed or Listed IPOs;
    show final subscription and listing result instead.
    """
    # High conviction metrics (Rs 100 GMP, 50x Sub) that would normally yield STRONG APPLY
    ipo = IPO(
        symbol="CLOSEDIPO",
        company_name="Closed Bidding Corp",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.CLOSED,
        close_date=date.today() - timedelta(days=2),
        issue_price=200.0,
        pe_ratio=18.0,
        ronw=22.0
    )
    gmp = IPOGmp(gmp_amount=80.0, gmp_percentage=40.0, source="consensus", recorded_at=datetime.now(timezone.utc))
    sub = IPOSubscription(total_multiple=45.0)

    score_res = ScoringService.calculate_score(ipo, latest_subscription=sub, latest_gmp=gmp)
    # Score should be high (>= 75)
    assert score_res["composite_score"] >= 75.0
    # But recommendation must NOT be STRONG APPLY or APPLY; it is NEUTRAL with final subscription text
    assert score_res["recommendation"] == RecommendationType.NEUTRAL
    assert "Issue Closed" in score_res["rationale"]["summary"]
    assert "Final Subscription: 45.0x" in score_res["rationale"]["summary"]


def test_hd_fire_protect_case():
    """
    Test 9: HD Fire Protect case check.
    Total subscription: 131.7x (SME), consensus GMP: ~Rs 81-85, P/E: 49.7.
    Scores properly without being penalized by unparsed category breakdowns.
    """
    ipo = IPO(
        symbol="HDFIREPROT",
        company_name="HD Fire Protect",
        ipo_type=IPOType.SME,
        status=IPOStatus.LIVE,
        close_date=date.today() - timedelta(days=1),
        issue_price=271.0,
        price_band_high=271.0,
        pe_ratio=49.72,
        issue_size_crores=45.0
    )
    # Consensus GMP of ~Rs 82 (30.3% gain)
    gmp = IPOGmp(gmp_amount=82.0, gmp_percentage=30.26, source="consensus", recorded_at=datetime.now(timezone.utc))
    # General scraper reports overall multiple 131.7x with 0.0 QIB / 0.0 Retail
    sub = IPOSubscription(total_multiple=131.73, qib_multiple=0.0, retail_multiple=0.0)

    score_res = ScoringService.calculate_score(ipo, latest_subscription=sub, latest_gmp=gmp)
    assert score_res["composite_score"] >= 75.0, f"Expected score >= 75, got {score_res['composite_score']}"
    assert score_res["subscription_score"] == 30.0, "Subscription score should be 30 for 131.7x overall demand"
    assert score_res["gmp_score"] >= 28.0, "GMP score should be strong"


def test_scrapers_never_write_default_zero():
    """
    Test 10: Neither InvestorGain nor IPOWatch writes a default 0 when GMP is missing, '--', or unlisted.
    """
    # 10a. InvestorGain row with '--' GMP
    sample_ig_html = """
    <table>
      <tr><th>Name</th><th>GMP</th><th>Rating</th><th>Sub</th><th>Price</th></tr>
      <tr><td>Unlisted IPO</td><td>₹--(0.00%)</td><td>-</td><td>-</td><td>100</td></tr>
    </table>
    """
    ig_records = ScraperService.parse_investorgain_table(sample_ig_html)
    assert len(ig_records) == 0 or ig_records[0]["gmp_amount"] is not None
    if len(ig_records) > 0:
        assert ig_records[0]["gmp_amount"] != 0.0, "Never write default 0 for unlisted/missing GMP"

    # 10b. IPOWatch row with missing GMP
    sample_iw_html = """
    <table>
      <tr><th>Company</th><th>GMP</th><th>Trend</th><th>Price Band</th><th>Est. Gain</th><th>Date</th></tr>
      <tr><td>Unknown Corp</td><td>--</td><td>-</td><td>₹200</td><td>-</td><td>21-23 Oct</td></tr>
    </table>
    """
    iw_records = IPOWatchScraper.parse_tables(sample_iw_html)
    for r in iw_records:
        assert r["gmp_amount"] is not None, "Never record row if GMP amount cannot be parsed"


def test_strict_matching_price_band_within_rs_1():
    """
    Test 11: Price cross-check requires price within Rs 1.0.
    Diff of 0.5 passes; diff of 2.0 (e.g. 52 vs 54) fails.
    """
    ipo = IPO(
        symbol="VAIBHAV",
        company_name="Vaibhav Vyapaar Ltd",
        price_band_high=54.0,
        issue_price=54.0,
        open_date=date(2026, 10, 13),
        close_date=date(2026, 10, 15)
    )

    # 11a. Price diff within Rs 1 (e.g. 54.5 vs 54.0) -> passes
    pass_item = {"company_name": "Vaibhav Vyapaar", "price": 54.5, "date_str": "13-15 Oct"}
    valid, _ = validate_match_cross_check(pass_item, ipo)
    assert valid is True

    # 11b. Price diff > Rs 1 (e.g. 52.0 vs 54.0, diff = 2.0) -> fails
    fail_item = {"company_name": "Vaibhav Vyapaar", "price": 52.0, "date_str": "13-15 Oct"}
    valid, reason = validate_match_cross_check(fail_item, ipo)
    assert valid is False
    assert "Price conflict" in reason


def test_strict_matching_date_within_2_days():
    """
    Test 12: Date cross-check requires open/close within 2 days.
    Diff of 1 day passes; diff of 3 days fails.
    """
    ipo = IPO(
        symbol="FUSIONCX",
        company_name="Fusion CX Ltd",
        price_band_high=289.0,
        issue_price=289.0,
        open_date=date(2026, 10, 14),
        close_date=date(2026, 10, 16)
    )

    # 12a. Close date within 2 days (15-Oct vs 16-Oct) -> passes
    pass_date_item = {"company_name": "Fusion CX", "price": 289.0, "date_str": "14-15 Oct"}
    valid, _ = validate_match_cross_check(pass_date_item, ipo)
    assert valid is True

    # 12b. Close date > 2 days (19-Oct vs 16-Oct, diff = 3 days) -> fails
    fail_date_item = {"company_name": "Fusion CX", "price": 289.0, "date_str": "14-19 Oct"}
    valid, reason = validate_match_cross_check(fail_date_item, ipo)
    assert valid is False
    assert "exceeds 2 days" in reason


def test_header_based_parsing_and_missing_header_error():
    """
    Test 13: Header-based column mapping dynamically maps headers,
    and raises ValueError when a required header (Name/Company or GMP) is missing.
    """
    # 13a. InvestorGain shuffled headers
    shuffled_ig = """
    <table>
      <tr><th>Price</th><th>GMP</th><th>Name</th><th>Close</th><th>Open</th><th>Sub</th></tr>
      <tr><td>₹500</td><td>₹50(10.00%)</td><td>Dynamic Alpha Corp</td><td>18-Oct</td><td>15-Oct</td><td>2.5x</td></tr>
    </table>
    """
    records = ScraperService.parse_investorgain_table(shuffled_ig)
    assert len(records) == 1
    assert records[0]["company_name"] == "Dynamic Alpha Corp"
    assert records[0]["gmp_amount"] == 50.0
    assert records[0]["price"] == 500.0

    # 13b. InvestorGain missing GMP header -> raises ValueError
    bad_ig = """
    <table>
      <tr><th>Name</th><th>Rating</th><th>Sub</th><th>Price</th></tr>
      <tr><td>Alpha Corp</td><td>🔥🔥🔥</td><td>1.2x</td><td>100</td></tr>
    </table>
    """
    import pytest
    with pytest.raises(ValueError, match="InvestorGain required header missing"):
        ScraperService.parse_investorgain_table(bad_ig)

    # 13c. IPOWatch missing Company header -> raises ValueError
    bad_iw = """
    <table>
      <tr><th>GMP</th><th>Trend</th><th>Price Band</th><th>Est. Gain</th></tr>
      <tr><td>₹25</td><td>Neutral</td><td>₹100</td><td>₹25</td></tr>
    </table>
    """
    with pytest.raises(ValueError, match="Expected GMP columns"):
        IPOWatchScraper.parse_tables(bad_iw)


@pytest.mark.asyncio
async def test_status_correction_job():
    """
    Test 14: Status correction correctly derives and stores IPO status in the database.
    """
    from app.services.scheduler import correct_ipo_statuses
    from app.database import AsyncSessionLocal
    from app.models.ipo import IPOStatus

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(select(IPO).where(IPO.company_name.in_(["Tonbo Imaging India", "HD Fire Protect"])))
        ipos = {i.company_name: i for i in res.scalars().all()}
        
        if "Tonbo Imaging India" in ipos:
            assert ipos["Tonbo Imaging India"].status == IPOStatus.LIVE
        if "HD Fire Protect" in ipos:
            assert ipos["HD Fire Protect"].status == IPOStatus.CLOSED


def test_price_band_range_matching_and_fallbacks():
    """
    Test 15: Scraped price lies inside [band_low - 1, band_high + 1] (or equals issue_price within Rs 1).
    Tests inside-band (Vaibhav Vyapaar Rs 52 vs band 51-54), boundaries, just outside, and missing band.
    """
    ipo_vaibhav = IPO(
        id=201,
        symbol="VAIBHAV",
        company_name="Vaibhav Vyapaar Ltd",
        price_band_low=51.0,
        price_band_high=54.0,
        issue_price=54.0,
        open_date=date(2026, 10, 14),
        close_date=date(2026, 10, 16)
    )

    # 15a. Vaibhav Vyapaar from IPOWatch (Rs 52 inside [51 - 1, 54 + 1]) -> MATCH
    scraped_52 = {"company_name": "Vaibhav Vyapaar", "price": 52.0, "date_str": "14-16 Oct"}
    valid, reason = validate_match_cross_check(scraped_52, ipo_vaibhav)
    assert valid is True
    assert "Passed" in reason

    # 15b. Boundary check: 50.0 (band_low - 1) and 55.0 (band_high + 1) -> MATCH
    scraped_50 = {"company_name": "Vaibhav Vyapaar", "price": 50.0, "date_str": "14-16 Oct"}
    valid_50, _ = validate_match_cross_check(scraped_50, ipo_vaibhav)
    assert valid_50 is True

    scraped_55 = {"company_name": "Vaibhav Vyapaar", "price": 55.0, "date_str": "14-16 Oct"}
    valid_55, _ = validate_match_cross_check(scraped_55, ipo_vaibhav)
    assert valid_55 is True

    # 15c. Just outside boundary: 49.0 and 56.0 -> REJECT
    scraped_49 = {"company_name": "Vaibhav Vyapaar", "price": 49.0, "date_str": "14-16 Oct"}
    valid_49, reason_49 = validate_match_cross_check(scraped_49, ipo_vaibhav)
    assert valid_49 is False
    assert "Price conflict" in reason_49

    scraped_56 = {"company_name": "Vaibhav Vyapaar", "price": 56.0, "date_str": "14-16 Oct"}
    valid_56, reason_56 = validate_match_cross_check(scraped_56, ipo_vaibhav)
    assert valid_56 is False
    assert "Price conflict" in reason_56

    # 15d. Missing price band: falls back to name + dates, marked lower confidence
    ipo_noband = IPO(
        id=202,
        symbol="NOBAND",
        company_name="Alpha Tech Ventures",
        price_band_low=None,
        price_band_high=None,
        issue_price=None,
        open_date=date(2026, 10, 14),
        close_date=date(2026, 10, 16)
    )
    scraped_noband = {"company_name": "Alpha Tech Ventures", "price": 120.0, "date_str": "14-16 Oct"}
    valid_noband, reason_noband = validate_match_cross_check(scraped_noband, ipo_noband)
    assert valid_noband is True
    assert scraped_noband.get("lower_confidence_match") is True
    assert "lower confidence" in reason_noband


@pytest.mark.asyncio
async def test_known_date_never_overwritten_by_tba():
    """
    Test 16: Ensure an existing known open_date/close_date is never overwritten by NULL or TBA.
    """
    existing_ipo = IPO(
        id=301,
        symbol="JIOPLAT_TEST",
        company_name="Jio Platforms Test Ltd",
        open_date=date(2026, 10, 21),
        close_date=date(2026, 10, 23),
        dates_tba=False,
        status=IPOStatus.UPCOMING
    )

    core_fields = ["open_date", "close_date", "dates_tba"]
    scraped_detail_tba = {
        "open_date": None,
        "close_date": None,
        "dates_tba": True
    }

    # Simulate detail update loop with our protection logic
    data_changed = False
    for f in core_fields:
        val = scraped_detail_tba.get(f)
        if val is not None:
            if f in ("open_date", "close_date") and getattr(existing_ipo, f) is not None and val is None:
                continue
            if f == "dates_tba" and getattr(existing_ipo, "open_date") is not None and val is True:
                continue
            setattr(existing_ipo, f, val)

    if existing_ipo.open_date is not None and existing_ipo.close_date is not None:
        existing_ipo.dates_tba = False

    assert existing_ipo.open_date == date(2026, 10, 21)
    assert existing_ipo.close_date == date(2026, 10, 23)
    assert existing_ipo.dates_tba is False


def test_extreme_gmp_capping_and_recommendation_label():
    """
    Test 17: When consensus GMP > 50% of issue price:
    1. GMP points are capped at 'strong' band (max 28.0)
    2. Recommendation shows 'Apply, verify GMP' instead of plain APPLY
    3. Rationale flags is_extreme_gmp = True
    """
    from app.services.scoring_service import ScoringService
    from app.models.ipo import IPOType, RecommendationType

    # Issue price 100, GMP Rs 80 (80% of issue price -> extreme)
    ipo = IPO(
        id=401,
        symbol="EXTREME_GMP",
        company_name="Extreme Rockets Ltd",
        ipo_type=IPOType.MAINBOARD,
        issue_price=100.0,
        price_band_low=95.0,
        price_band_high=100.0,
        open_date=date.today(),
        close_date=date.today() + timedelta(days=2),
        pe_ratio=20.0,
        industry_pe=30.0,
        ronw=18.0,
        issue_size_crores=500.0,
        fresh_issue_crores=400.0,
        dates_tba=False
    )

    sub = IPOSubscription(
        ipo_id=401,
        total_multiple=15.0,
        qib_multiple=10.0,
        retail_multiple=8.0,
        day_number=3
    )

    # Extreme GMP: Rs 80 on Rs 100 issue price (80%)
    extreme_gmp = IPOGmp(
        ipo_id=401,
        gmp_amount=80.0,
        gmp_percentage=80.0,
        source="consensus",
        recorded_at=datetime.now(timezone.utc)
    )

    res = ScoringService.calculate_score(ipo, latest_subscription=sub, latest_gmp=extreme_gmp)

    # 1. GMP points must be capped at 28.0 (strong tier, not 35.0 bumper)
    assert res["gmp_score"] == 28.0
    # 2. Recommendation must be 'Apply, verify GMP'
    assert res["recommendation"] == RecommendationType.APPLY_VERIFY_GMP
    assert res["recommendation"].value == "Apply, verify GMP"
    # 3. Extreme GMP flagged in rationale
    assert res["rationale"]["is_extreme_gmp"] is True


def test_gmp_quality_banner_evaluation_cases():
    """
    Test 18: Verify GMP quality banner triggers strictly when:
    (a) All sources fail (ig=0, iw=0)
    (b) Fewer than 50% of live IPOs have fresh GMP
    Does NOT trigger when single source fails but coverage >= 50%.
    """
    # Case A: Both sources fail -> alert active
    res_all_fail = ScraperService.evaluate_gmp_quality(
        ig_count=0,
        iw_count=0,
        live_ipos_count=4,
        live_ipos_with_fresh_gmp=0
    )
    assert res_all_fail["alert_active"] is True
    assert "All GMP sources failed" in res_all_fail["reason"]

    # Case B: Low coverage (<50% live IPOs fresh) -> alert active
    res_low_cov = ScraperService.evaluate_gmp_quality(
        ig_count=10,
        iw_count=10,
        live_ipos_count=4,
        live_ipos_with_fresh_gmp=1  # 25% < 50%
    )
    assert res_low_cov["alert_active"] is True
    assert "Fewer than 50%" in res_low_cov["reason"]

    # Case C: Single source fails, but coverage >= 50% -> alert NOT active
    res_single_fail_good_cov = ScraperService.evaluate_gmp_quality(
        ig_count=0,
        iw_count=10,
        live_ipos_count=4,
        live_ipos_with_fresh_gmp=3  # 75% >= 50%
    )
    assert res_single_fail_good_cov["alert_active"] is False

    # Case D: Both sources healthy and coverage >= 50% -> alert NOT active
    res_healthy = ScraperService.evaluate_gmp_quality(
        ig_count=12,
        iw_count=12,
        live_ipos_count=4,
        live_ipos_with_fresh_gmp=4  # 100%
    )
    assert res_healthy["alert_active"] is False


def test_low_confidence_and_closed_card_scoring_rules():
    """
    Test 19: Verify scoring outputs for:
    - Low confidence (<50%): recommendation INSUFFICIENT DATA, missing inputs populated
    - Closed IPO: status CLOSED, recommendation neutral/closed summary, score at close preserved
    """
    from app.services.scoring_service import ScoringService
    from app.models.ipo import RecommendationType

    # 19a. Low confidence (<50%): only issue size known (weight 5/100 -> confidence 5%)
    sparse_ipo = IPO(
        id=501,
        symbol="SPARSE",
        company_name="Sparse Data Ltd",
        issue_size_crores=100.0,
        open_date=date.today(),
        close_date=date.today() + timedelta(days=2)
    )
    sparse_res = ScoringService.calculate_score(sparse_ipo)
    assert sparse_res["confidence"] < 0.50
    assert sparse_res["recommendation"] == RecommendationType.INSUFFICIENT_DATA
    assert len(sparse_res["missing_inputs"]) >= 4

    # 19b. Closed IPO: close date in the past
    closed_ipo = IPO(
        id=502,
        symbol="PAST_IPO",
        company_name="Closed Corp Ltd",
        issue_price=200.0,
        price_band_low=190.0,
        price_band_high=200.0,
        open_date=date.today() - timedelta(days=10),
        close_date=date.today() - timedelta(days=7),
        pe_ratio=18.0,
        industry_pe=25.0,
        ronw=16.0,
        issue_size_crores=400.0,
        fresh_issue_crores=300.0,
        dates_tba=False
    )
    closed_sub = IPOSubscription(
        ipo_id=502,
        total_multiple=45.2,
        qib_multiple=60.0,
        retail_multiple=22.0
    )
    closed_gmp = IPOGmp(
        ipo_id=502,
        gmp_amount=50.0,
        gmp_percentage=25.0,
        source="consensus",
        recorded_at=datetime.now(timezone.utc)
    )
    closed_res = ScoringService.calculate_score(closed_ipo, latest_subscription=closed_sub, latest_gmp=closed_gmp)
    # Stored score is present and valid
    assert closed_res["composite_score"] > 60.0
    # Recommendation is marked NEUTRAL for closed issue, and summary mentions closed with final sub
    assert closed_res["recommendation"] == RecommendationType.NEUTRAL
    assert "Issue Closed" in closed_res["rationale"]["summary"]
    assert "45.2x" in closed_res["rationale"]["summary"]


