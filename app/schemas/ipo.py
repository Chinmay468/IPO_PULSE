import enum
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
    listing_price: Optional[float] = Field(default=None, ge=0)
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

    source: Optional[str] = None
    source_url: Optional[str] = None
    source_id: Optional[int] = None
    fetched_at: Optional[datetime] = None
    data_quality: Optional[Dict[str, Any]] = None
    is_seed: bool = False
    dates_tba: bool = False


# ---------------- Scraper Child Entities Schemas ----------------
class IPODocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    type: str
    url: str
    created_at: datetime


class IPOAnchorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    investor: str
    amount: Optional[float] = None
    lock_in_end: Optional[date] = None
    created_at: datetime


class IPOReviewsSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    apply: int = 0
    may_apply: int = 0
    neutral: int = 0
    avoid: int = 0
    not_rated: int = 0
    fetched_at: datetime


class IPOListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ipo_id: int
    listing_price: Optional[float] = None
    listing_gain_pct: Optional[float] = None
    listing_date: Optional[date] = None
    fetched_at: datetime


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
    listing_price: Optional[float] = None
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
    data_incomplete: bool = False
    day_label: Optional[str] = None
    is_dates_unavailable: bool = False

    # Scraper relations
    documents: List[IPODocumentResponse] = Field(default_factory=list)
    anchor_investors: List[IPOAnchorResponse] = Field(default_factory=list)
    reviews_summary: Optional[IPOReviewsSummaryResponse] = None
    listing_info: Optional[IPOListingResponse] = None


class IPODetailResponse(IPOResponse):
    model_config = ConfigDict(from_attributes=True)

    subscriptions: List[SubscriptionResponse] = Field(default_factory=list)
    gmp_records: List[GMPResponse] = Field(default_factory=list)


class IPOListResponse(BaseModel):
    total: int
    items: List[IPOResponse]


# ---------------- Allotment Schemas ----------------
class AllotmentQueryType(str, enum.Enum):
    PAN = "PAN"
    APPLICATION_NO = "APPLICATION_NO"
    DP_CLIENT_ID = "DP_CLIENT_ID"


class AllotmentStatus(str, enum.Enum):
    ALLOTTED = "ALLOTTED"
    NOT_ALLOTTED = "NOT_ALLOTTED"
    NOT_FOUND = "NOT_FOUND"
    PENDING = "PENDING"
    ERROR = "ERROR"


class RegistrarCompanyItem(BaseModel):
    company_id: str = Field(..., description="Unique company identifier on the registrar system")
    company_name: str = Field(..., description="Company name as shown on registrar portal")


class AllotmentQueryRequest(BaseModel):
    company_id: str = Field(..., description="Company identifier on Link Intime (e.g. '1052' or 'TATATECH')")
    query_type: AllotmentQueryType = Field(default=AllotmentQueryType.PAN, description="PAN, APPLICATION_NO, or DP_CLIENT_ID")
    query_value: str = Field(..., description="The PAN number, application number, or DP ID / Client ID")


class AllotmentResultResponse(BaseModel):
    success: bool
    status: AllotmentStatus
    company_name: str
    company_id: str
    applicant_name: Optional[str] = None
    pan: Optional[str] = None
    application_no: Optional[str] = None
    dp_client_id: Optional[str] = None
    shares_applied: Optional[int] = None
    shares_allotted: Optional[int] = None
    refund_amount: Optional[float] = None
    message: str
    source_registrar: str = "Link Intime"


class AllotmentIPOItem(BaseModel):
    id: int
    symbol: str
    company_name: str
    status: str
    ipo_type: str
    registrar_name: Optional[str] = None
    registrar_code: Optional[str] = None
    registrar_allotment_url: Optional[str] = None
    allotment_date: Optional[date] = None
    supported_inline: bool = False
    open_date: Optional[date] = None
    close_date: Optional[date] = None
    listing_date: Optional[date] = None


class AllotmentIPOsResponse(BaseModel):
    ipos: List[AllotmentIPOItem]
    total: int
    message: Optional[str] = None
