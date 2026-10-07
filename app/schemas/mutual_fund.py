"""
Pydantic schemas for the Mutual Funds module.
"""
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.mutual_fund import MFTransactionType


# ── Scheme Schemas ────────────────────────────────────────────────────────────

class MFSchemeBase(BaseModel):
    scheme_code: Optional[str] = None
    isin: Optional[str] = None
    name: str
    amc: Optional[str] = None
    category: Optional[str] = None
    plan_type: Optional[str] = None
    option_type: Optional[str] = None


class MFSchemeResponse(MFSchemeBase):
    id: int
    latest_nav: Optional[float] = None
    latest_nav_date: Optional[date] = None
    is_nav_stale: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Transaction Schemas ───────────────────────────────────────────────────────

class MFTransactionCreate(BaseModel):
    date: date
    type: MFTransactionType = MFTransactionType.BUY
    units: float = Field(gt=0)
    nav: float = Field(gt=0)
    amount: float = Field(gt=0)


class MFTransactionResponse(BaseModel):
    id: int
    holding_id: int
    date: date
    type: MFTransactionType
    units: float
    nav: float
    amount: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Holding Schemas ───────────────────────────────────────────────────────────

class MFHoldingCreate(BaseModel):
    scheme_name: str
    scheme_code: Optional[str] = None
    isin: Optional[str] = None
    amc: Optional[str] = None
    category: Optional[str] = None
    folio_masked: Optional[str] = None
    units: float = Field(ge=0)
    avg_nav: Optional[float] = Field(default=None, ge=0)


class MFHoldingUpdate(BaseModel):
    units: Optional[float] = Field(default=None, ge=0)
    folio_masked: Optional[str] = None


class MFHoldingItemResponse(BaseModel):
    id: int
    scheme_id: int
    scheme_name: str
    scheme_code: Optional[str] = None
    isin: Optional[str] = None
    amc: Optional[str] = None
    category: Optional[str] = None
    folio_masked: Optional[str] = None
    units: float
    avg_nav: float
    latest_nav: Optional[float] = None
    latest_nav_date: Optional[date] = None
    is_nav_stale: bool = False
    invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    xirr: Optional[float] = None
    transactions: List[MFTransactionResponse] = []


# ── Summary & Allocation Schemas ──────────────────────────────────────────────

class AllocationItem(BaseModel):
    name: str
    value: float
    percentage: float


class MFSummaryResponse(BaseModel):
    total_invested: float
    current_value: float
    total_pnl: float
    total_pnl_pct: float
    overall_xirr: Optional[float] = None
    holdings_count: int
    priced_count: int
    unpriced_count: int
    unpriced_holdings: List[str] = []
    nav_as_of_date: Optional[date] = None
    category_allocation: List[AllocationItem] = []
    amc_allocation: List[AllocationItem] = []
    holdings: List[MFHoldingItemResponse] = []


class MFNavHistoryPoint(BaseModel):
    date: date
    nav: float


class MFSchemeHistoryResponse(BaseModel):
    scheme_id: int
    scheme_name: str
    scheme_code: Optional[str] = None
    history: List[MFNavHistoryPoint] = []


# ── Net Worth Combined Schema ─────────────────────────────────────────────────

class StockBreakdown(BaseModel):
    invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    holdings_count: int
    unpriced_count: int


class MFBreakdown(BaseModel):
    invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    overall_xirr: Optional[float] = None
    holdings_count: int
    unpriced_count: int
    nav_as_of_date: Optional[date] = None


class CombinedNetWorthResponse(BaseModel):
    total_net_worth: float
    total_invested: float
    total_pnl: float
    total_pnl_pct: float
    stocks: StockBreakdown
    mutual_funds: MFBreakdown


# ── CAS Import Response ───────────────────────────────────────────────────────

class CASImportResponse(BaseModel):
    status: str = "success"
    schemes_created: int
    holdings_created: int
    transactions_imported: int
    transactions_skipped: int
    message: str
