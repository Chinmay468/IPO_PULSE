import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import asyncio
import time
import pandas as pd
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.portfolio import Holding, Transaction, TransactionType, PortfolioSnapshot
from app.schemas.portfolio import (
    HoldingCreate, HoldingUpdate, TransactionCreate, HoldingResponse, PortfolioSummary,
    PortfolioSnapshotResponse, HoldingHistoryResponse, OHLCVItem, IndicatorPoint
)
from app.services.market_price_service import get_live_prices_bulk, _yf_symbol, _clean_ticker
from app.services.portfolio_advisor_service import get_recent_closes_bulk
from app.services.technical_analysis_service import compute_wilder_rsi, compute_technical_diagnosis, DISCLAIMER_TEXT

logger = logging.getLogger(__name__)

# In-memory history cache: (yf_symbol, range_str) -> (result_dict, expiry_timestamp)
_history_cache: dict[tuple[str, str], tuple[dict, float]] = {}


# ── Holdings CRUD ────────────────────────────────────────────────────────────

async def list_holdings(db: AsyncSession, user_id: Optional[int] = None) -> list[Holding]:
    stmt = select(Holding).options(selectinload(Holding.transactions)).order_by(Holding.symbol)
    if user_id is not None:
        stmt = stmt.where(Holding.user_id == user_id)
    else:
        stmt = stmt.where(Holding.user_id.is_(None))
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_holding(db: AsyncSession, holding_id: int, user_id: Optional[int] = None) -> Optional[Holding]:
    stmt = (
        select(Holding)
        .where(Holding.id == holding_id)
        .options(selectinload(Holding.transactions))
    )
    if user_id is not None:
        stmt = stmt.where(Holding.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_holding_by_symbol(
    db: AsyncSession, symbol: str, exchange: str, user_id: Optional[int] = None
) -> Optional[Holding]:
    stmt = (
        select(Holding)
        .where(Holding.symbol == symbol.upper(), Holding.exchange == exchange)
        .options(selectinload(Holding.transactions))
    )
    if user_id is not None:
        stmt = stmt.where(Holding.user_id == user_id)
    else:
        stmt = stmt.where(Holding.user_id.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_holding(db: AsyncSession, data: HoldingCreate, user_id: Optional[int] = None) -> Holding:
    holding = Holding(
        symbol=data.symbol.upper(),
        company_name=data.company_name,
        exchange=data.exchange,
        quantity=data.quantity,
        avg_buy_price=data.avg_buy_price,
        ipo_symbol=data.ipo_symbol,
        user_id=user_id,
    )
    db.add(holding)
    await db.flush()  # get ID before adding transaction

    # Auto-create the first BUY transaction
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=TransactionType.BUY,
        quantity=data.quantity,
        price=data.avg_buy_price,
        transaction_date=data.initial_transaction_date or date.today(),
        notes="Initial position"
    )
    db.add(txn)
    await db.commit()
    return await get_holding(db, holding.id, user_id=user_id)


async def update_holding(
    db: AsyncSession, holding_id: int, data: HoldingUpdate, user_id: Optional[int] = None
) -> Optional[Holding]:
    holding = await get_holding(db, holding_id, user_id=user_id)
    if not holding:
        return None
    if data.company_name is not None:
        holding.company_name = data.company_name
    if data.quantity is not None:
        holding.quantity = data.quantity
    if data.avg_buy_price is not None:
        holding.avg_buy_price = data.avg_buy_price
    await db.commit()
    return await get_holding(db, holding_id, user_id=user_id)


async def delete_holding(db: AsyncSession, holding_id: int, user_id: Optional[int] = None) -> bool:
    holding = await get_holding(db, holding_id, user_id=user_id)
    if not holding:
        return False
    await db.delete(holding)
    await db.commit()
    return True


# ── Transactions ─────────────────────────────────────────────────────────────

async def add_transaction(
    db: AsyncSession, holding_id: int, data: TransactionCreate, user_id: Optional[int] = None
) -> Optional[Transaction]:
    holding = await get_holding(db, holding_id, user_id=user_id)
    if not holding:
        return None

    txn = Transaction(
        holding_id=holding_id,
        transaction_type=data.transaction_type,
        quantity=data.quantity,
        price=data.price,
        transaction_date=data.transaction_date,
        notes=data.notes,
    )
    db.add(txn)

    # Recalculate avg_buy_price on BUY
    if data.transaction_type == TransactionType.BUY:
        total_cost = (holding.avg_buy_price * holding.quantity) + (data.price * data.quantity)
        holding.quantity += data.quantity
        holding.avg_buy_price = round(total_cost / holding.quantity, 4) if holding.quantity > 0 else 0

    # Reduce quantity on SELL
    elif data.transaction_type == TransactionType.SELL:
        holding.quantity = max(0, holding.quantity - data.quantity)

    await db.commit()
    await db.refresh(txn)
    return txn


# ── Portfolio Summary (with live prices) ─────────────────────────────────────

async def get_portfolio_summary(db: AsyncSession, user_id: Optional[int] = None) -> PortfolioSummary:
    holdings = await list_holdings(db, user_id=user_id)

    if not holdings:
        return PortfolioSummary(
            total_invested=0, current_value=0, total_unrealized_pnl=0,
            total_pnl_pct=0, day_change=0, day_change_pct=0,
            holdings_count=0, gainers=0, losers=0,
            unpriced_count=0, unpriced_symbols=[],
            holdings=[]
        )

    # Bulk fetch live prices and 7-day trend closes
    sym_exch_pairs = [(h.symbol, h.exchange.value) for h in holdings]
    live_prices = await get_live_prices_bulk(sym_exch_pairs)
    yf_symbols = [_yf_symbol(h.symbol, h.exchange.value) for h in holdings]
    recent_closes = await get_recent_closes_bulk(yf_symbols, count=7)

    enriched: list[HoldingResponse] = []
    priced_invested = 0.0
    current_value = 0.0
    day_change = 0.0
    gainers = losers = 0
    unpriced_count = 0
    unpriced_symbols: list[str] = []

    for h in holdings:
        yf_key = _yf_symbol(h.symbol, h.exchange.value)
        live_price, day_change_pct = live_prices.get(yf_key, (None, None))

        invested = round(h.avg_buy_price * h.quantity, 2)
        curr_val = round(live_price * h.quantity, 2) if live_price is not None else None
        unrealized_pnl = round(curr_val - invested, 2) if curr_val is not None else None
        pnl_pct = round(((curr_val - invested) / invested) * 100, 2) if curr_val is not None and invested > 0 else None

        if live_price is not None:
            priced_invested += invested
            current_value += curr_val
            if day_change_pct:
                prev_val = curr_val / (1 + day_change_pct / 100)
                day_change += (curr_val - prev_val)
            if unrealized_pnl is not None:
                if unrealized_pnl > 0:
                    gainers += 1
                elif unrealized_pnl < 0:
                    losers += 1
        else:
            unpriced_count += 1
            unpriced_symbols.append(h.symbol)

        enriched.append(HoldingResponse(
            id=h.id,
            symbol=h.symbol,
            company_name=h.company_name,
            exchange=h.exchange,
            quantity=h.quantity,
            avg_buy_price=h.avg_buy_price,
            ipo_symbol=h.ipo_symbol,
            created_at=h.created_at,
            updated_at=h.updated_at,
            live_price=live_price,
            current_value=curr_val,
            invested_value=invested,
            unrealized_pnl=unrealized_pnl,
            pnl_pct=pnl_pct,
            day_change_pct=day_change_pct,
            trend_closes=recent_closes.get(yf_key) or None,
            transactions=[],  # omit in summary for performance
        ))

    total_invested = round(priced_invested, 2)
    current_value = round(current_value, 2)
    overall_pnl = round(current_value - total_invested, 2)
    overall_pnl_pct = round((overall_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0
    day_chg_pct = round((day_change / (current_value - day_change)) * 100, 2) if (current_value - day_change) > 0 else 0.0

    return PortfolioSummary(
        total_invested=total_invested,
        current_value=current_value,
        total_unrealized_pnl=overall_pnl,
        total_pnl_pct=overall_pnl_pct,
        day_change=round(day_change, 2),
        day_change_pct=day_chg_pct,
        holdings_count=len(holdings),
        gainers=gainers,
        losers=losers,
        unpriced_count=unpriced_count,
        unpriced_symbols=unpriced_symbols,
        holdings=enriched,
        last_updated=datetime.now(timezone.utc),
    )


# ── Portfolio Valuation Snapshots ───────────────────────────────────────────

async def take_portfolio_snapshot(
    db: AsyncSession, snapshot_date: Optional[date] = None, user_id: Optional[int] = None
) -> PortfolioSnapshot:
    """
    Saves a daily post-market valuation snapshot using priced holdings only.
    Upserts the record if a snapshot already exists for the given date.
    """
    if snapshot_date is None:
        ist_tz = ZoneInfo("Asia/Kolkata")
        snapshot_date = datetime.now(ist_tz).date()

    summary = await get_portfolio_summary(db, user_id=user_id)
    priced_count = summary.holdings_count - summary.unpriced_count

    # Check if a snapshot already exists for this date and user
    stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.date == snapshot_date)
    if user_id is not None:
        stmt = stmt.where(PortfolioSnapshot.user_id == user_id)
    else:
        stmt = stmt.where(PortfolioSnapshot.user_id.is_(None))
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot:
        snapshot.invested = summary.total_invested
        snapshot.current_value = summary.current_value
        snapshot.pnl = summary.total_unrealized_pnl
        snapshot.priced_count = priced_count
    else:
        snapshot = PortfolioSnapshot(
            date=snapshot_date,
            invested=summary.total_invested,
            current_value=summary.current_value,
            pnl=summary.total_unrealized_pnl,
            priced_count=priced_count,
            user_id=user_id,
        )
        db.add(snapshot)

    await db.commit()
    await db.refresh(snapshot)
    logger.info(
        "[PortfolioSnapshot] Recorded snapshot for %s (user=%s): invested=%.2f, current=%.2f, pnl=%.2f, priced_count=%d",
        snapshot_date, user_id, snapshot.invested, snapshot.current_value, snapshot.pnl, snapshot.priced_count
    )
    return snapshot


async def get_portfolio_snapshots(db: AsyncSession, user_id: Optional[int] = None) -> list[PortfolioSnapshot]:
    """Retrieve all historical portfolio snapshots ordered chronologically."""
    stmt = select(PortfolioSnapshot).order_by(PortfolioSnapshot.date.asc())
    if user_id is not None:
        stmt = stmt.where(PortfolioSnapshot.user_id == user_id)
    else:
        stmt = stmt.where(PortfolioSnapshot.user_id.is_(None))
    result = await db.execute(stmt)
    return result.scalars().all()


# ── Holding Price History & Indicators ───────────────────────────────────────

def _fetch_history_sync(yf_sym: str, lookback: str) -> pd.DataFrame:
    import yfinance as yf
    tkr = yf.Ticker(yf_sym)
    return tkr.history(period=lookback, interval="1d", auto_adjust=True)


async def get_holding_history(symbol: str, range_str: str, db: AsyncSession) -> dict:
    range_str = range_str.lower().strip()
    if range_str not in ("1m", "3m", "6m", "1y"):
        range_str = "3m"

    clean_sym = _clean_ticker(symbol)

    # Check if this stock is in portfolio holdings to retrieve user's avg cost basis
    result = await db.execute(
        select(Holding).where(Holding.symbol == clean_sym.upper())
    )
    holding = result.scalars().first()
    avg_cost = holding.avg_buy_price if holding else None
    exchange = holding.exchange.value if holding else "NSE"
    yf_sym = _yf_symbol(clean_sym, exchange)

    # Cache check
    cache_key = (yf_sym, range_str)
    now_ts = time.time()
    cached = _history_cache.get(cache_key)
    if cached:
        cached_data, expiry_ts = cached
        if now_ts < expiry_ts:
            res = dict(cached_data)
            res["avg_cost"] = avg_cost
            return res

    lookback_map = {
        "1m": "6mo",  # generous lookback to ensure EMA50 & RSI14 warmup
        "3m": "1y",
        "6m": "1y",
        "1y": "2y",
    }
    lookback = lookback_map.get(range_str, "1y")

    loop = asyncio.get_running_loop()
    try:
        df = await loop.run_in_executor(None, _fetch_history_sync, yf_sym, lookback)
    except Exception as exc:
        logger.warning("[HoldingHistory] yfinance fetch failed for %s: %s", yf_sym, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch market history from yfinance for {symbol}: {str(exc)}"
        )

    # If primary exchange yielded no rows, try alternate exchange (.BO <-> .NS)
    if df is None or df.empty:
        alt_sym = f"{clean_sym}.BO" if yf_sym.endswith(".NS") else f"{clean_sym}.NS"
        try:
            df = await loop.run_in_executor(None, _fetch_history_sync, alt_sym, lookback)
            if df is not None and not df.empty:
                yf_sym = alt_sym
        except Exception:
            pass

    if df is None or df.empty:
        return {
            "symbol": symbol,
            "range": range_str,
            "candles": [],
            "ema20": [],
            "ema50": [],
            "rsi14": [],
            "avg_cost": avg_cost,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "insufficient_history": True,
            "message": "No price history available from yfinance"
        }

    # Timezone conversion to IST
    ist_tz = ZoneInfo("Asia/Kolkata")
    if df.index.tz is None:
        df.index = df.index.tz_localize(ist_tz)
    else:
        df.index = df.index.tz_convert(ist_tz)

    close = df['Close'].dropna()
    total_candles = len(close)

    if total_candles < 10:
        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": float(row.get("Volume", 0)),
            })
        return {
            "symbol": symbol,
            "range": range_str,
            "candles": candles,
            "ema20": [],
            "ema50": [],
            "rsi14": [],
            "avg_cost": avg_cost,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "insufficient_history": True,
            "message": "Fewer than 10 candles available"
        }

    # Technical Indicators across full data using shared unified functions
    ema20_series = close.ewm(span=20, adjust=False).mean()
    ema50_series = close.ewm(span=min(50, len(close)), adjust=False).mean()
    rsi14_series = compute_wilder_rsi(close, period=14)

    tech = compute_technical_diagnosis(df, avg_buy_price=avg_cost or float(close.iloc[-1]))
    stop_loss = tech.get("stop_loss")
    trailing_stop = tech.get("trailing_stop")
    target_1 = tech.get("target_1")
    target_2 = tech.get("target_2")

    # Slice to range
    days_map = {"1m": 31, "3m": 93, "6m": 186, "1y": 366}
    days_back = days_map.get(range_str, 93)
    cutoff = df.index[-1] - timedelta(days=days_back)
    sliced_df = df[df.index >= cutoff]

    if len(sliced_df) < 10:
        insufficient_history = True
    else:
        insufficient_history = False

    candles = []
    ema20_list = []
    ema50_list = []
    rsi14_list = []

    for idx, row in sliced_df.iterrows():
        t_str = idx.strftime("%Y-%m-%d")
        candles.append({
            "time": t_str,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": float(row.get("Volume", 0)),
        })
        if idx in ema20_series.index and not pd.isna(ema20_series.loc[idx]):
            ema20_list.append({"time": t_str, "value": round(float(ema20_series.loc[idx]), 2)})
        if idx in ema50_series.index and not pd.isna(ema50_series.loc[idx]):
            ema50_list.append({"time": t_str, "value": round(float(ema50_series.loc[idx]), 2)})
        if idx in rsi14_series.index and not pd.isna(rsi14_series.loc[idx]):
            rsi14_list.append({"time": t_str, "value": round(float(rsi14_series.loc[idx]), 2)})

    res_data = {
        "symbol": symbol,
        "range": range_str,
        "candles": candles,
        "ema20": ema20_list,
        "ema50": ema50_list,
        "rsi14": rsi14_list,
        "avg_cost": avg_cost,
        "stop_loss": stop_loss,
        "trailing_stop": trailing_stop,
        "target_1": target_1,
        "target_2": target_2,
        "target_1_label": "estimated",
        "target_2_label": "estimated",
        "disclaimer": DISCLAIMER_TEXT,
        "insufficient_history": insufficient_history,
        "message": "Fewer than 10 candles in range" if insufficient_history else None
    }

    # Cache TTL: 15 min if latest candle is today (IST), 24h for older/static ranges
    latest_candle_date = sliced_df.index[-1].date()
    today_ist = datetime.now(ist_tz).date()
    ttl_seconds = 900 if latest_candle_date == today_ist else 86400

    _history_cache[cache_key] = (res_data, now_ts + ttl_seconds)
    return res_data


# ── Backwards-Compatibility Namespace ───────────────────────────────────────
class _PortfolioServiceProxy:
    get_portfolio_summary = staticmethod(get_portfolio_summary)
    list_holdings = staticmethod(list_holdings)
    get_holding = staticmethod(get_holding)
    get_holding_by_symbol = staticmethod(get_holding_by_symbol)
    take_portfolio_snapshot = staticmethod(take_portfolio_snapshot)
    get_portfolio_snapshots = staticmethod(get_portfolio_snapshots)
    get_holding_history = staticmethod(get_holding_history)

portfolio_service = _PortfolioServiceProxy()



