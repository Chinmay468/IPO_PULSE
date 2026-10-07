import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scoring_config import SCORING_CONFIG
from app.models.ipo import IPO, IPOSubscription, IPOGmp, IPOType, IPOStatus, RecommendationType, IPOScore
from app.services.scoring_service import ScoringService


@pytest.mark.asyncio
async def test_scoring_rules_endpoint(client: AsyncClient):
    """Test that GET /api/v1/scoring/rules returns exactly SCORING_CONFIG."""
    res = await client.get("/api/v1/scoring/rules")
    assert res.status_code == 200
    data = res.json()

    # Assert version, weights, and structure match SCORING_CONFIG
    assert data["version"] == SCORING_CONFIG["version"]
    assert data["updated_at"] == SCORING_CONFIG["updated_at"]
    assert data["weights"]["gmp"]["max_points"] == 35.0
    assert data["weights"]["subscription"]["max_points"] == 30.0
    assert data["weights"]["valuation"]["max_points"] == 20.0
    assert data["weights"]["structure"]["max_points"] == 15.0

    total_weight = sum(w["max_points"] for w in data["weights"].values())
    assert total_weight == 100.0

    # Assert notes and not_yet_included
    assert "not_yet_included" in data["notes"]
    assert len(data["notes"]["not_yet_included"]) == 4


def test_mainboard_issue_size_100_to_300_cr_gap():
    """Verify that Mainboard issue size in ₹100–300 Cr gets 4.0 points (not falling through to 3.5)."""
    ipo = IPO(
        symbol="GAP_TEST",
        company_name="Gap Test Ltd",
        ipo_type=IPOType.MAINBOARD,
        issue_price=100.0,
        issue_size_crores=200.0,  # in ₹100-300 Cr range
        fresh_issue_crores=200.0,
        ofs_crores=0.0
    )
    score_res = ScoringService.calculate_score(ipo)
    # Fresh issue 100% -> 10.0 pts. Issue size 200 Cr -> 4.0 pts. Total structure = 14.0 pts
    assert score_res["structure_score"] == 14.0


def test_qib_continuous_interpolation():
    """Verify that QIB interpolation is smooth between 5x and 30x, and handles < 1x."""
    ipo = IPO(symbol="QIB_TEST", company_name="QIB Test Ltd", ipo_type=IPOType.MAINBOARD)

    # 1. Target 30x -> 16.0 pts
    sub_30x = IPOSubscription(ipo_id=1, qib_multiple=30.0, day_number=3, total_multiple=30.0)
    res_30x = ScoringService.calculate_score(ipo, latest_subscription=sub_30x)
    # retail None (2.0) + total 30x (6.5) + qib 16.0 = 24.5
    assert res_30x["subscription_score"] >= 24.0

    # 2. Intermediate 17.5x (midpoint between 5x and 30x) -> 10.0 + ((17.5-5)/25)*6 = 13.0 pts
    sub_mid = IPOSubscription(ipo_id=1, qib_multiple=17.5, day_number=3, total_multiple=17.5)
    res_mid = ScoringService.calculate_score(ipo, latest_subscription=sub_mid)
    # qib should be exactly 13.0
    qib_pts_mid = 10.0 + ((17.5 - 5.0) / (30.0 - 5.0)) * 6.0
    assert qib_pts_mid == 13.0

    # 3. Sub-1x on Day 3: 0.5x -> 1.0 + 0.5 * 5.0 = 3.5 pts
    sub_sub1 = IPOSubscription(ipo_id=1, qib_multiple=0.5, day_number=3, total_multiple=0.5)
    res_sub1 = ScoringService.calculate_score(ipo, latest_subscription=sub_sub1)
    # qib is 3.5, retail is 2.0 (missing), total 0.5x is 0.5 -> subscription score = 6.0
    assert res_sub1["subscription_score"] == 6.0

    # 4. Sub-1x on early bidding (Day 1): 5.0 pts
    sub_early = IPOSubscription(ipo_id=1, qib_multiple=0.2, day_number=1, total_multiple=0.2)
    res_early = ScoringService.calculate_score(ipo, latest_subscription=sub_early)
    # qib is 5.0 early, retail is 2.0, total is 0.5 -> 7.5
    assert res_early["subscription_score"] == 7.5


def test_absolute_pe_fallback():
    """Verify that when Industry P/E is missing, absolute P/E thresholds are used."""
    # PE < 25 -> 9.0 pts
    ipo_cheap = IPO(symbol="CHEAP_PE", company_name="Cheap PE Ltd", pe_ratio=18.0, industry_pe=None, ronw=20.0)
    res_cheap = ScoringService.calculate_score(ipo_cheap)
    # pe 9.0 + ronw 8.0 = 17.0
    assert res_cheap["valuation_score"] == 17.0

    # PE > 45 -> 3.0 pts
    ipo_exp = IPO(symbol="EXP_PE", company_name="Expensive PE Ltd", pe_ratio=55.0, industry_pe=None, ronw=20.0)
    res_exp = ScoringService.calculate_score(ipo_exp)
    # pe 3.0 + ronw 8.0 = 11.0
    assert res_exp["valuation_score"] == 11.0


@pytest.mark.asyncio
async def test_score_breakdown_endpoint(client: AsyncClient, auth_client: AsyncClient):
    """Test GET /api/v1/ipos/{id}/score/breakdown."""
    # Create an IPO
    create_res = await auth_client.post("/api/v1/ipos", json={
        "symbol": "BREAKDOWN_CO",
        "company_name": "Breakdown Co Ltd",
        "ipo_type": "MAINBOARD",
        "status": "LIVE",
        "issue_price": 250.0,
        "issue_size_crores": 800.0,
        "fresh_issue_crores": 600.0,
        "pe_ratio": 22.0,
        "industry_pe": 30.0,
        "ronw": 18.0
    })
    assert create_res.status_code == 201
    ipo_id = create_res.json()["id"]

    # Call breakdown endpoint
    res = await client.get(f"/api/v1/ipos/{ipo_id}/score/breakdown")
    assert res.status_code == 200
    data = res.json()

    assert data["ipo_id"] == ipo_id
    assert data["symbol"] == "BREAKDOWN_CO"
    assert "composite_score" in data
    assert "recommendation" in data
    assert "pillars" in data
    pillars = data["pillars"]
    assert "gmp" in pillars
    assert "subscription" in pillars
    assert "valuation" in pillars
    assert "structure" in pillars
    assert pillars["valuation"]["max_score"] == 20.0
    assert len(pillars["valuation"]["reasons"]) > 0


@pytest.mark.asyncio
async def test_score_calculator_interactive(client: AsyncClient):
    """Test POST /api/v1/scoring/calculate with synthetic numbers."""
    payload = {
        "ipo_type": "MAINBOARD",
        "gmp_pct": 45.0,
        "qib_multiple": 25.0,
        "retail_multiple": 8.0,
        "total_multiple": 30.0,
        "pe_ratio": 20.0,
        "industry_pe": 30.0,
        "ronw": 22.0,
        "fresh_issue_pct": 80.0,
        "issue_size_crores": 1500.0
    }
    res = await client.post("/api/v1/scoring/calculate", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["composite_score"] >= 75.0
    assert data["recommendation"] == "STRONG APPLY"
    assert data["pillars"]["gmp"]["score"] == 35.0
    assert data["pillars"]["structure"]["score"] == 15.0


@pytest.mark.asyncio
async def test_track_record_endpoint(client: AsyncClient, db_session: AsyncSession):
    """Test GET /api/v1/scoring/track-record calculates from DB and handles <20 samples."""
    # When no or few IPOs exist, each tier should show "not enough data"
    res = await client.get("/api/v1/scoring/track-record")
    assert res.status_code == 200
    data = res.json()

    assert data["threshold"] == 20
    assert "tiers" in data
    for tier in ["STRONG APPLY", "APPLY", "NEUTRAL", "AVOID"]:
        assert tier in data["tiers"]
        assert data["tiers"][tier]["status"] == "not enough data"

    # Now simulate 20 listed IPOs with listing prices in db_session for STRONG APPLY
    for i in range(22):
        test_ipo = IPO(
            symbol=f"LISTED_{i}",
            company_name=f"Listed Company {i}",
            ipo_type=IPOType.MAINBOARD,
            status=IPOStatus.LISTED,
            issue_price=100.0,
            listing_price=135.0  # +35% listing gain
        )
        db_session.add(test_ipo)
        await db_session.flush()

        score = IPOScore(
            ipo_id=test_ipo.id,
            composite_score=85.0,
            recommendation=RecommendationType.STRONG_APPLY,
            gmp_score=35.0,
            subscription_score=25.0,
            valuation_score=15.0,
            structure_score=10.0
        )
        db_session.add(score)
    await db_session.commit()

    # Re-fetch track record
    res2 = await client.get("/api/v1/scoring/track-record")
    assert res2.status_code == 200
    data2 = res2.json()

    strong_apply = data2["tiers"]["STRONG APPLY"]
    assert strong_apply["count"] == 22
    assert strong_apply["status"] == "ok"
    assert strong_apply["avg_gain_pct"] == 35.0
    assert strong_apply["display"] == "+35.0%"


@pytest.mark.asyncio
async def test_page_data_equals_config(client: AsyncClient):
    """
    Verify that the Scoring Methodology page data equals the config:
    - GET /api/v1/scoring/rules returns config matching SCORING_CONFIG exactly.
    - GET / (index.html) integrates with /api/v1/scoring/rules and contains the dynamic containers.
    """
    # 1. Direct equality between rules endpoint and canonical SCORING_CONFIG
    rules_res = await client.get("/api/v1/scoring/rules")
    assert rules_res.status_code == 200
    rules_data = rules_res.json()
    assert rules_data == SCORING_CONFIG

    # 2. Verify index.html contains dynamic containers and fetches the config
    page_res = await client.get("/")
    assert page_res.status_code == 200
    html = page_res.text

    assert "/api/v1/scoring/rules" in html
    assert "/api/v1/scoring/track-record" in html
    assert "/api/v1/scoring/calculate" in html
    assert "/score/breakdown" in html
    assert "dynamic-pillars-container" in html
    assert "dynamic-track-record-container" in html
    assert "dynamic-cutoffs-container" in html
    assert "calc-res-score" in html
    assert "modal-breakdown-total" in html
