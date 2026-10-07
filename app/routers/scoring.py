from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.ipo import IPO, IPOScore, IPOStatus, RecommendationType
from app.core.scoring_config import SCORING_CONFIG
from app.services.scoring_service import ScoringService

router = APIRouter(prefix="/scoring", tags=["Scoring Engine & Rules"])


class CalculatorRequest(BaseModel):
    ipo_type: str = Field(default="MAINBOARD", description="MAINBOARD or SME")
    gmp_pct: Optional[float] = Field(default=None, description="Grey Market Premium percentage (e.g. 25.5)")
    subject_to_sauda: Optional[float] = Field(default=None, description="Subject to Sauda price in INR")
    qib_multiple: Optional[float] = Field(default=None, description="QIB subscription multiple (e.g. 15.0)")
    retail_multiple: Optional[float] = Field(default=None, description="Retail subscription multiple (e.g. 5.0)")
    total_multiple: Optional[float] = Field(default=None, description="Total subscription multiple (e.g. 18.0)")
    day_number: Optional[int] = Field(default=3, description="Bidding day (1, 2, 3)")
    pe_ratio: Optional[float] = Field(default=None, description="Company P/E multiple")
    industry_pe: Optional[float] = Field(default=None, description="Industry average P/E multiple")
    ronw: Optional[float] = Field(default=None, description="Return on Net Worth %")
    fresh_issue_pct: Optional[float] = Field(default=None, description="Fresh issue percentage of total (e.g. 80.0)")
    issue_size_crores: Optional[float] = Field(default=None, description="Total issue size in Crores (e.g. 500.0)")


@router.get("/rules", summary="Get canonical scoring thresholds, weights, and interpolation rules")
async def get_scoring_rules() -> Dict[str, Any]:
    """
    Returns the canonical, institutional-grade scoring configuration.
    Used by both backend calculations and the frontend Scoring Methodology page.
    """
    return SCORING_CONFIG


@router.post("/calculate", summary="Interactive what-if score calculator")
async def calculate_score_interactive(data: CalculatorRequest) -> Dict[str, Any]:
    """
    Runs real-time score calculation against user-provided parameters
    using the exact backend ScoringService engine.
    """
    result = ScoringService.calculate_synthetic(
        ipo_type=data.ipo_type,
        gmp_pct=data.gmp_pct,
        subject_to_sauda=data.subject_to_sauda,
        qib_multiple=data.qib_multiple,
        retail_multiple=data.retail_multiple,
        total_multiple=data.total_multiple,
        day_number=data.day_number,
        pe_ratio=data.pe_ratio,
        industry_pe=data.industry_pe,
        ronw=data.ronw,
        fresh_issue_pct=data.fresh_issue_pct,
        issue_size_crores=data.issue_size_crores
    )

    rec_val = result["recommendation"]
    if hasattr(rec_val, "value"):
        rec_val = rec_val.value

    return {
        "composite_score": result["composite_score"],
        "recommendation": rec_val,
        "gmp_score": result["gmp_score"],
        "subscription_score": result["subscription_score"],
        "valuation_score": result["valuation_score"],
        "structure_score": result["structure_score"],
        "pillars": result["pillars"],
        "rationale": result["rationale"]
    }


@router.get("/track-record", summary="Empirical historical track record of listed IPOs by tier")
async def get_track_record(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Computes count and average listing gain % for listed IPOs with verified listing prices,
    segmented by recommendation tier (STRONG APPLY, APPLY, NEUTRAL, AVOID).
    Strictly reports 'not enough data' for any tier with fewer than 20 IPOs.
    """
    # Query all IPOs with their associated score
    stmt = (
        select(IPO, IPOScore)
        .outerjoin(IPOScore, IPO.id == IPOScore.ipo_id)
        .where(
            (IPO.status == IPOStatus.LISTED) | (IPO.listing_price.isnot(None))
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    tiers_data: Dict[str, Dict[str, Any]] = {
        "STRONG APPLY": {"count": 0, "gains": [], "badge": "badge-STRONG_APPLY"},
        "APPLY": {"count": 0, "gains": [], "badge": "badge-APPLY"},
        "NEUTRAL": {"count": 0, "gains": [], "badge": "badge-NEUTRAL"},
        "AVOID": {"count": 0, "gains": [], "badge": "badge-AVOID"},
    }

    total_listed = 0
    for ipo, score in rows:
        base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low
        listing_price = getattr(ipo, "listing_price", None)

        if listing_price is not None and base_price is not None and base_price > 0:
            total_listed += 1
            gain_pct = round(((listing_price - base_price) / base_price) * 100.0, 2)

            rec_tier = "AVOID"
            if score and score.recommendation:
                rec_val = score.recommendation.value if hasattr(score.recommendation, "value") else str(score.recommendation)
                if rec_val in tiers_data:
                    rec_tier = rec_val

            tiers_data[rec_tier]["count"] += 1
            tiers_data[rec_tier]["gains"].append(gain_pct)

    summary: Dict[str, Any] = {}
    for tier_name, data in tiers_data.items():
        count = data["count"]
        if count >= 20:
            avg_gain = round(sum(data["gains"]) / count, 2)
            summary[tier_name] = {
                "count": count,
                "avg_gain_pct": avg_gain,
                "status": "ok",
                "display": f"+{avg_gain:.1f}%" if avg_gain > 0 else f"{avg_gain:.1f}%"
            }
        else:
            summary[tier_name] = {
                "count": count,
                "avg_gain_pct": None,
                "status": "not enough data",
                "display": "Not enough data (<20 IPOs)"
            }

    return {
        "threshold": 20,
        "total_evaluated_listed": total_listed,
        "tiers": summary,
        "note": "Empirical listing performance computed from verified database records. Tiers with under 20 listings are withheld to prevent statistical sample bias."
    }
