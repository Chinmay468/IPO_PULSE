from datetime import date, datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, Field, computed_field
from app.models.ipo import IPOType, IPOStatus, RecommendationType


# ---------------- Subscription Schemas ----------------
class SubscriptionBase(BaseModel):
    qib_multiple: Optional[float] = Field(default=0.0, description="QIB subscription multiple (e.g. 15.4)")
    nii_multiple: Optional[float] = Field(default=0.0, description="NII subscription multiple (e.g. 8.2)")
    retail_multiple: Optional[float] = Field(default=0.0, description="Retail subscription multiple (e.g. 3.5)")
    employee_multiple: Optional[float] = Field(default=0.0, description="Employee subscription multiple")
    total_multiple: float = Field(..., description="Overall subscription multiple")

    qib_shares_offered: Optional[float] = None
    qib_shares_bid: Optional[float] = None
    nii_shares_offered: Optional[float] = None
    nii_shares_bid: Optional[float] = None
    retail_shares_offered: Optional[float] = None
    retail_shares_bid: Optional[float] = None
    total_shares_offered: Optional[float] = None
    total_shares_bid: Optional[float] = None

    day_number: Optional[int] = Field(default=None, description="Bidding day (1, 2, 3)")


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionResponse(SubscriptionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    recorded_at: datetime


# ---------------- GMP Schemas ----------------
class GMPBase(BaseModel):
    gmp_amount: float = Field(..., description="Grey Market Premium in INR (e.g. 140.0)")
    gmp_percentage: float = Field(..., description="Estimated percentage listing gain (e.g. 28.5)")
    estimated_listing_price: Optional[float] = Field(default=None, description="Expected listing price in INR")
    kostak_rate: Optional[float] = Field(default=None, description="Kostak rate in INR")
    subject_to_sauda: Optional[float] = Field(default=None, description="Subject to sauda price in INR")
    source: str = Field(default="market", description="Data source (e.g. investorgain, chittorgarh)")


class GMPCreate(GMPBase):
    pass


class GMPResponse(GMPBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    recorded_at: datetime


# ---------------- Scoring Schemas ----------------
class ScoreBreakdown(BaseModel):
    gmp_score: float = Field(..., description="Score points contributed by GMP (max 35)")
    subscription_score: float = Field(..., description="Score points contributed by Subscription demand (max 30)")
    valuation_score: float = Field(..., description="Score points contributed by Valuation vs Peers (max 20)")
    structure_score: float = Field(..., description="Score points contributed by Fresh Issue vs OFS (max 15)")
    rationale: Optional[Dict[str, Any]] = Field(default=None, description="Detailed explanatory factors")


class ScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    ipo_id: int
    composite_score: float = Field(..., description="Composite score out of 100")
    recommendation: RecommendationType = Field(..., description="STRONG APPLY, APPLY, NEUTRAL, or AVOID")
    gmp_score: float
    subscription_score: float
    valuation_score: float
    structure_score: float
    rationale: Optional[Dict[str, Any]] = None
    calculated_at: datetime


# ---------------- IPO Master Schemas ----------------
class IPOBase(BaseModel):
    symbol: str = Field(..., max_length=50, description="NSE/BSE Trading symbol or unique slug")
    company_name: str = Field(..., max_length=255, description="Full legal name of the issuing company")
    ipo_type: IPOType = Field(default=IPOType.MAINBOARD, description="MAINBOARD or SME")
    status: IPOStatus = Field(default=IPOStatus.UPCOMING, description="UPCOMING, LIVE, CLOSED, or LISTED")

    price_band_low: Optional[float] = Field(default=None, ge=0)
    price_band_high: Optional[float] = Field(default=None, ge=0)
    issue_price: Optional[float] = Field(default=None, ge=0)
    lot_size: Optional[int] = Field(default=None, ge=1)

    issue_size_crores: Optional[float] = Field(default=None, ge=0)
    fresh_issue_crores: Optional[float] = Field(default=None, ge=0)
    ofs_crores: Optional[float] = Field(default=None, ge=0)

    open_date: Optional[date] = None
    close_date: Optional[date] = None
    allotment_date: Optional[date] = None
    refunds_initiation_date: Optional[date] = None
    demat_credit_date: Optional[date] = None
    listing_date: Optional[date] = None

    registrar_name: Optional[str] = Field(default=None, max_length=100)
    registrar_code: Optional[str] = Field(default=None, max_length=100)

    pe_ratio: Optional[float] = None
    industry_pe: Optional[float] = None
    ronw: Optional[float] = None
    eps: Optional[float] = None

    sector: Optional[str] = None
    revenue_growth_yoy: Optional[float] = None
    pat_growth_yoy: Optional[float] = None
    debt_to_equity: Optional[float] = None
    pat_margin_pct: Optional[float] = None
    promoter_holding_pre: Optional[float] = None
    promoter_holding_post: Optional[float] = None


class IPOCreate(IPOBase):
    pass


class IPOUpdate(BaseModel):
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    ipo_type: Optional[IPOType] = None
    status: Optional[IPOStatus] = None

    price_band_low: Optional[float] = None
    price_band_high: Optional[float] = None
    issue_price: Optional[float] = None
    lot_size: Optional[int] = None

    issue_size_crores: Optional[float] = None
    fresh_issue_crores: Optional[float] = None
    ofs_crores: Optional[float] = None

    open_date: Optional[date] = None
    close_date: Optional[date] = None
    allotment_date: Optional[date] = None
    refunds_initiation_date: Optional[date] = None
    demat_credit_date: Optional[date] = None
    listing_date: Optional[date] = None

    registrar_name: Optional[str] = None
    registrar_code: Optional[str] = None

    pe_ratio: Optional[float] = None
    industry_pe: Optional[float] = None
    ronw: Optional[float] = None
    eps: Optional[float] = None


class IPOResponse(IPOBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

    # Computed or joined fields
    latest_gmp: Optional[GMPResponse] = None
    latest_subscription: Optional[SubscriptionResponse] = None
    score: Optional[ScoreResponse] = None
    angelone_apply_url: Optional[str] = None
    can_apply: bool = False
    is_pre_apply: bool = False


class IPODetailResponse(IPOResponse):
    model_config = ConfigDict(from_attributes=True)

    subscriptions: List[SubscriptionResponse] = Field(default_factory=list)
    gmp_records: List[GMPResponse] = Field(default_factory=list)


class IPOListResponse(BaseModel):
    total: int
    items: List[IPOResponse]
