from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from app.models.portfolio import Exchange, TransactionType


# ── Transaction Schemas ──────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    transaction_type: TransactionType
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    transaction_date: date
    notes: Optional[str] = None


class TransactionResponse(BaseModel):
    id: int
    holding_id: int
    transaction_type: TransactionType
    quantity: float
    price: float
    transaction_date: date
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Holding Schemas ──────────────────────────────────────────────────────────

class HoldingCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    company_name: str = Field(..., min_length=1, max_length=255)
    exchange: Exchange = Exchange.NSE
    quantity: float = Field(..., gt=0)
    avg_buy_price: float = Field(..., gt=0)
    ipo_symbol: Optional[str] = None
    initial_transaction_date: Optional[date] = None  # Used for the first buy transaction


class HoldingUpdate(BaseModel):
    company_name: Optional[str] = None
    quantity: Optional[float] = Field(None, gt=0)
    avg_buy_price: Optional[float] = Field(None, gt=0)


class HoldingResponse(BaseModel):
    id: int
    symbol: str
    company_name: str
    exchange: Exchange
    quantity: float
    avg_buy_price: float
    ipo_symbol: Optional[str]
    created_at: datetime
    updated_at: datetime
    # Live-enriched fields (populated by service layer)
    live_price: Optional[float] = None
    current_value: Optional[float] = None
    invested_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    day_change_pct: Optional[float] = None
    trend_closes: Optional[list[float]] = None
    transactions: list[TransactionResponse] = []

    model_config = {"from_attributes": True}


# ── Portfolio Summary ────────────────────────────────────────────────────────

class PortfolioSummary(BaseModel):
    total_invested: float
    current_value: float
    total_unrealized_pnl: float
    total_pnl_pct: float
    day_change: float
    day_change_pct: float
    holdings_count: int
    gainers: int
    losers: int
    unpriced_count: int = 0
    unpriced_symbols: list[str] = []
    holdings: list[HoldingResponse]
    last_updated: Optional[datetime] = None


# ── Snapshot Schemas ─────────────────────────────────────────────────────────

class PortfolioSnapshotResponse(BaseModel):
    id: int
    date: date
    invested: float
    current_value: float
    pnl: float
    priced_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Holding History & Indicator Schemas ──────────────────────────────────────

class OHLCVItem(BaseModel):
    time: str  # YYYY-MM-DD IST date string for Lightweight Charts
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorPoint(BaseModel):
    time: str
    value: float


class HoldingHistoryResponse(BaseModel):
    symbol: str
    range: str
    candles: list[OHLCVItem] = []
    ema20: list[IndicatorPoint] = []
    ema50: list[IndicatorPoint] = []
    rsi14: list[IndicatorPoint] = []
    avg_cost: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    insufficient_history: bool = False
    message: Optional[str] = None


# ── Angel One Diagnostic Schemas ─────────────────────────────────────────────

class AngelOneEnvStatus(BaseModel):
    api_key_set: bool
    client_id_set: bool
    password_set: bool
    totp_secret_set: bool


class AngelOneLastSyncStatus(BaseModel):
    step: Optional[str] = None
    error_class: Optional[str] = None
    error_code: Optional[str] = None
    timestamp: Optional[datetime] = None
    success: Optional[bool] = None


class AngelOneDiagnoseResponse(BaseModel):
    egress_ipv4: Optional[str] = None
    egress_ipv6: Optional[str] = None
    time_offset_seconds: Optional[float] = None
    ntp_sync_ok: bool = False
    env_vars: AngelOneEnvStatus
    last_failure: AngelOneLastSyncStatus


