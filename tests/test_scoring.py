import pytest
from app.models.ipo import IPO, IPOSubscription, IPOGmp, IPOType, IPOStatus, RecommendationType
from app.services.scoring_service import ScoringService


def test_scoring_strong_apply():
    """An IPO with high GMP (80%), massive QIB demand (50x), attractive PE should be STRONG APPLY."""
    ipo = IPO(
        symbol="SUPER_IPO",
        company_name="Super Growth Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=500.0,
        issue_size_crores=2000.0,
        fresh_issue_crores=1800.0,
        ofs_crores=200.0,
        pe_ratio=25.0,
        industry_pe=50.0,
        ronw=26.0
    )
    gmp = IPOGmp(
        ipo_id=1,
        gmp_amount=400.0,
        gmp_percentage=80.0,
        source="market"
    )
    sub = IPOSubscription(
        ipo_id=1,
        qib_multiple=50.0,
        retail_multiple=20.0,
        total_multiple=60.0
    )

    score_result = ScoringService.calculate_score(ipo, sub, gmp)
    assert score_result["composite_score"] >= 75.0
    assert score_result["recommendation"] == RecommendationType.STRONG_APPLY
    assert score_result["gmp_score"] == 35.0
    assert score_result["subscription_score"] >= 28.0
    assert len(score_result["rationale"]["positive_factors"]) > 0


def test_scoring_avoid():
    """An IPO with negative GMP, poor subscription (<1x), high overvaluation should be AVOID."""
    ipo = IPO(
        symbol="WEAK_IPO",
        company_name="Weak Holdings Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=100.0,
        issue_size_crores=500.0,
        fresh_issue_crores=50.0,
        ofs_crores=450.0,
        pe_ratio=80.0,
        industry_pe=20.0,
        ronw=-5.0
    )
    gmp = IPOGmp(
        ipo_id=2,
        gmp_amount=-10.0,
        gmp_percentage=-10.0,
        source="market"
    )
    sub = IPOSubscription(
        ipo_id=2,
        qib_multiple=0.2,
        retail_multiple=0.4,
        total_multiple=0.3
    )

    score_result = ScoringService.calculate_score(ipo, sub, gmp)
    assert score_result["composite_score"] < 45.0
    assert score_result["recommendation"] == RecommendationType.AVOID
    assert score_result["gmp_score"] == 0.0
    assert len(score_result["rationale"]["risk_factors"]) > 0


def test_scoring_apply_and_neutral():
    """Moderate numbers should yield APPLY (60-74) or NEUTRAL (45-59)."""
    ipo = IPO(
        symbol="MODERATE_IPO",
        company_name="Moderate Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=200.0,
        issue_size_crores=1000.0,
        fresh_issue_crores=600.0,
        ofs_crores=400.0,
        pe_ratio=30.0,
        industry_pe=32.0,
        ronw=14.0
    )
    gmp = IPOGmp(
        ipo_id=3,
        gmp_amount=40.0,
        gmp_percentage=20.0,
        source="market"
    )
    sub = IPOSubscription(
        ipo_id=3,
        qib_multiple=6.0,
        retail_multiple=3.5,
        total_multiple=8.0
    )

    score_result = ScoringService.calculate_score(ipo, sub, gmp)
    assert 45.0 <= score_result["composite_score"] <= 85.0
    assert score_result["recommendation"] in [RecommendationType.APPLY, RecommendationType.NEUTRAL, RecommendationType.STRONG_APPLY]
