"""
Price History Service.
Manages the persistent daily price-history data layer, historical backfills,
daily market-close sync, data quality validation, chart integration with transactions,
portfolio valuation history, streaming exports (CSV/XLSX/Parquet), and research hooks.
"""

import asyncio
import io
import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional, Set
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from sqlalchemy import select, func, and_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import Holding, Transaction, TransactionType
from app.models.price_history import PriceHistory, DataIssue
from app.services.nse_holidays import is_trading_day, get_trading_days, get_missing_trading_days
from app.services.price_validation import validate_candle
from app.services.prediction_service import DEFAULT_WATCHLIST

logger = logging.getLogger("price_history_service")
IST = ZoneInfo("Asia/Kolkata")


def clean_symbol(sym: str) -> str:
    """Strips exchange suffix and whitespace from symbol."""
    return sym.upper().replace(".NS", "").replace(".BO", "").strip()


def yf_symbol(sym: str, exchange: str = "NSE") -> str:
    """Formats symbol for yfinance query (.NS or .BO)."""
    clean = clean_symbol(sym)
    if clean == "^NSEI":
        return clean
    if exchange.upper() == "BSE":
        return f"{clean}.BO"
    return f"{clean}.NS"


def _fetch_yf_candles_sync(
    yf_sym: str,
    period: str = "5y",
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_retries: int = 3,
    backoff_factor: float = 1.5
) -> pd.DataFrame:
    """
    Synchronously fetches historical OHLCV data from yfinance with exponential backoff.
    Handles listings with short history cleanly.
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            ticker = yf.Ticker(yf_sym)
            if start and end:
                df = ticker.history(start=start, end=end, auto_adjust=False, actions=True)
            elif start:
                df = ticker.history(start=start, auto_adjust=False, actions=True)
            else:
                df = ticker.history(period=period, auto_adjust=False, actions=True)

            if df is not None and not df.empty:
                return df

            # If empty and .NS, try .BO fallback (or vice versa)
            alt_sym = f"{clean_symbol(yf_sym)}.BO" if yf_sym.endswith(".NS") else f"{clean_symbol(yf_sym)}.NS"
            alt_ticker = yf.Ticker(alt_sym)
            if start and end:
                df_alt = alt_ticker.history(start=start, end=end, auto_adjust=False, actions=True)
            elif start:
                df_alt = alt_ticker.history(start=start, auto_adjust=False, actions=True)
            else:
                df_alt = alt_ticker.history(period=period, auto_adjust=False, actions=True)

            if df_alt is not None and not df_alt.empty:
                return df_alt

            # Empty returned (may be newly listed or no trades)
            return pd.DataFrame()
        except Exception as exc:
            last_err = exc
            logger.warning("[PriceHistory] Attempt %d/%d failed for %s: %s", attempt, max_retries, yf_sym, exc)
            if attempt < max_retries:
                time.sleep(backoff_factor ** attempt)

    logger.error("[PriceHistory] All %d retries failed for %s: %s", max_retries, yf_sym, last_err)
    if last_err is not None:
        raise last_err
    return pd.DataFrame()


async def execute_upsert_candles(
    db: AsyncSession,
    rows: List[Dict[str, Any]]
) -> int:
    """
    Idempotently upserts candle rows into price_history on (symbol, exchange, date).
    Supports both SQLite and PostgreSQL.
    """
    if not rows:
        return 0

    conn = await db.connection()
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

    stmt = dialect_insert(PriceHistory).values(rows)
    update_cols = {
        "open": stmt.excluded.open,
        "high": stmt.excluded.high,
        "low": stmt.excluded.low,
        "close": stmt.excluded.close,
        "adj_close": stmt.excluded.adj_close,
        "volume": stmt.excluded.volume,
        "source": stmt.excluded.source,
        "fetched_at": func.now()
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "exchange", "date"],
        set_=update_cols
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def validate_and_upsert_raw_candles(
    db: AsyncSession,
    symbol: str,
    exchange: str,
    df: pd.DataFrame,
    source: str = "yfinance"
) -> Dict[str, Any]:
    """
    Validates all candles in the DataFrame, logs issues/flags to data_issues,
    and upserts valid candles into price_history.
    """
    clean_sym = clean_symbol(symbol)
    exchange_upper = exchange.upper()

    if df is None or df.empty:
        return {"symbol": clean_sym, "upserted": 0, "rejected": 0, "issues": 0}

    # Ensure index is datetime and localized/converted to IST
    if df.index.tz is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)

    # Sort chronologically
    df = df.sort_index()

    # Retrieve existing latest price before this slice to calculate first price jump/gap
    first_date = df.index[0].date()
    prev_row_query = await db.execute(
        select(PriceHistory.date, PriceHistory.close)
        .where(PriceHistory.symbol == clean_sym, PriceHistory.exchange == exchange_upper, PriceHistory.date < first_date)
        .order_by(desc(PriceHistory.date))
        .limit(1)
    )
    prev_db_row = prev_row_query.first()
    prev_date = prev_db_row[0] if prev_db_row else None
    prev_close = prev_db_row[1] if prev_db_row else None

    valid_rows = []
    issues_to_insert = []
    rejected_count = 0

    for dt, row in df.iterrows():
        candle_date = dt.date()
        open_val = float(row["Open"]) if pd.notna(row.get("Open")) else None
        high_val = float(row["High"]) if pd.notna(row.get("High")) else None
        low_val = float(row["Low"]) if pd.notna(row.get("Low")) else None
        close_val = float(row["Close"]) if pd.notna(row.get("Close")) else None
        
        # Look for Adj Close or fall back to Close
        adj_close_val = None
        if "Adj Close" in row and pd.notna(row["Adj Close"]):
            adj_close_val = float(row["Adj Close"])
        elif close_val is not None:
            adj_close_val = close_val

        volume_val = int(row["Volume"]) if pd.notna(row.get("Volume")) else 0

        is_valid, candle_issues = validate_candle(
            symbol=clean_sym,
            exchange=exchange_upper,
            d=candle_date,
            open_val=open_val,
            high_val=high_val,
            low_val=low_val,
            close_val=close_val,
            adj_close_val=adj_close_val,
            volume_val=volume_val,
            prev_date=prev_date,
            prev_close=prev_close
        )

        for iss in candle_issues:
            issues_to_insert.append(DataIssue(**iss))

        if is_valid:
            valid_rows.append({
                "symbol": clean_sym,
                "exchange": exchange_upper,
                "date": candle_date,
                "open": round(open_val, 4),
                "high": round(high_val, 4),
                "low": round(low_val, 4),
                "close": round(close_val, 4),
                "adj_close": round(adj_close_val, 4) if adj_close_val is not None else None,
                "volume": volume_val,
                "source": source
            })
            prev_date = candle_date
            prev_close = close_val
        else:
            rejected_count += 1

    # Record issues
    if issues_to_insert:
        db.add_all(issues_to_insert)
        await db.commit()

    # Batch upsert valid rows
    upserted_count = await execute_upsert_candles(db, valid_rows)

    return {
        "symbol": clean_sym,
        "upserted": upserted_count,
        "rejected": rejected_count,
        "issues": len(issues_to_insert)
    }


async def backfill_symbol(
    db: AsyncSession,
    symbol: str,
    exchange: str = "NSE",
    years: int = 5,
    sleep_sec: float = 0.5
) -> Dict[str, Any]:
    """
    Backfills up to `years` of historical daily candles from yfinance for a symbol.
    Sleeps between calls to avoid rate limiting.
    """
    clean_sym = clean_symbol(symbol)
    yf_sym = yf_symbol(clean_sym, exchange)
    period = f"{years}y"

    logger.info("[PriceHistory] Backfilling %s (%s) for %s...", clean_sym, yf_sym, period)
    df = await asyncio.to_thread(_fetch_yf_candles_sync, yf_sym, period=period)

    res = await validate_and_upsert_raw_candles(db, clean_sym, exchange, df)

    if sleep_sec > 0:
        await asyncio.sleep(sleep_sec)

    return res


async def get_all_tracked_symbols(db: AsyncSession) -> List[Tuple[str, str]]:
    """
    Returns deduplicated list of (symbol, exchange) tuples across:
    1. Active portfolio holdings
    2. Default liquid watchlist
    """
    symbols_map: Dict[str, str] = {}

    # 1. Holdings
    holdings_res = await db.execute(select(Holding.symbol, Holding.exchange))
    for sym, ex in holdings_res.all():
        clean = clean_symbol(sym)
        ex_val = ex.value if hasattr(ex, "value") else str(ex)
        symbols_map[clean] = ex_val or "NSE"

    # 2. Watchlist
    for sym in DEFAULT_WATCHLIST:
        clean = clean_symbol(sym)
        if clean not in symbols_map:
            symbols_map[clean] = "NSE"

    return list(symbols_map.items())


async def backfill_all_symbols(
    db: AsyncSession,
    years: int = 5,
    sleep_sec: float = 0.5
) -> Dict[str, Any]:
    """
    Backfills all tracked symbols (holdings + watchlist) up to `years`.
    Returns summary statistics and row counts per symbol.
    """
    tracked = await get_all_tracked_symbols(db)
    logger.info("[PriceHistory] Starting backfill for %d tracked symbols...", len(tracked))

    results = []
    total_upserted = 0
    total_rejected = 0
    total_issues = 0

    for sym, ex in tracked:
        try:
            r = await backfill_symbol(db, sym, exchange=ex, years=years, sleep_sec=sleep_sec)
            results.append(r)
            total_upserted += r.get("upserted", 0)
            total_rejected += r.get("rejected", 0)
            total_issues += r.get("issues", 0)
        except Exception as exc:
            logger.error("[PriceHistory] Error backfilling %s: %s", sym, exc)
            results.append({"symbol": sym, "error": str(exc), "upserted": 0})

    return {
        "symbols_processed": len(tracked),
        "total_upserted": total_upserted,
        "total_rejected": total_rejected,
        "total_issues": total_issues,
        "details": results
    }


async def daily_market_close_sync(db: AsyncSession) -> Dict[str, Any]:
    """
    Scheduled daily job running after market close (~6 PM IST) on trading days only.
    Fetches latest candles for each tracked symbol and upserts them.
    Never writes zeros or copies previous day.
    """
    now_ist = datetime.now(IST)
    today_date = now_ist.date()

    if not is_trading_day(today_date):
        logger.info("[PriceHistory Daily Sync] Skipped: %s is not an active NSE trading day.", today_date)
        return {"status": "skipped", "reason": f"{today_date} is not an NSE trading day", "upserted": 0}

    tracked = await get_all_tracked_symbols(db)
    logger.info("[PriceHistory Daily Sync] Fetching latest candles for %d tracked symbols...", len(tracked))

    upserted_count = 0
    failed_symbols = []

    for sym, ex in tracked:
        yf_sym = yf_symbol(sym, ex)
        try:
            # Fetch last 5 days to ensure the closed day is reliably captured
            df = await asyncio.to_thread(_fetch_yf_candles_sync, yf_sym, period="5d")
            if df is not None and not df.empty:
                # Upsert through validation
                res = await validate_and_upsert_raw_candles(db, sym, ex, df)
                upserted_count += res.get("upserted", 0)
            else:
                logger.warning("[PriceHistory Daily Sync] No candle returned for %s", yf_sym)
                failed_symbols.append(sym)
        except Exception as exc:
            logger.error("[PriceHistory Daily Sync] Error for %s: %s", sym, exc)
            failed_symbols.append(sym)

        await asyncio.sleep(0.3)

    return {
        "status": "completed",
        "date": str(today_date),
        "tracked_count": len(tracked),
        "upserted_count": upserted_count,
        "failed_symbols": failed_symbols
    }


async def get_price_history_with_fallback(
    db: AsyncSession,
    symbol: str,
    range_str: str = "3m",
    adjusted: bool = True
) -> Dict[str, Any]:
    """
    Primary endpoint reader for charts:
    1. Reads from price_history first.
    2. Falls back to yfinance only for missing days and saves them.
    3. Returns raw and adjusted series with flag.
    4. Attaches BUY and SELL markers from portfolio_transactions.
    5. Calculates EMA20, EMA50, RSI14, avg cost, stop loss, trailing stop, and targets.
    """
    from app.services.portfolio_service import (
        compute_wilder_rsi,
        compute_technical_diagnosis,
        DISCLAIMER_TEXT
    )

    clean_sym = clean_symbol(symbol)
    range_str = range_str.lower().strip()
    if range_str not in ("1m", "3m", "6m", "1y", "5y"):
        range_str = "3m"

    days_map = {"1m": 31, "3m": 93, "6m": 186, "1y": 366, "5y": 1826}
    days_back = days_map.get(range_str, 93)
    today_date = datetime.now(IST).date()
    start_date = today_date - timedelta(days=days_back + 100)  # buffer for EMAs/RSI

    # Check holding info for avg cost & markers
    holding_res = await db.execute(
        select(Holding).where(Holding.symbol == clean_sym)
    )
    holding = holding_res.scalars().first()
    avg_cost = holding.avg_buy_price if holding else None
    exchange = holding.exchange.value if holding else "NSE"

    # Query local price_history
    ph_res = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.symbol == clean_sym,
            PriceHistory.date >= start_date
        )
        .order_by(asc(PriceHistory.date))
    )
    cached_candles = ph_res.scalars().all()

    # Determine if fallback is needed
    needs_fallback = False
    if len(cached_candles) < 10:
        needs_fallback = True
    else:
        # Check if the latest candle in DB is stale on an active trading day after 18:00 IST
        latest_db_date = cached_candles[-1].date
        if is_trading_day(today_date) and latest_db_date < today_date:
            now_hour = datetime.now(IST).hour
            if now_hour >= 18:
                needs_fallback = True

    last_fetch_error = None
    if needs_fallback:
        logger.info("[PriceHistory] Falling back to yfinance for %s (have %d candles)...", clean_sym, len(cached_candles))
        yf_sym = yf_symbol(clean_sym, exchange)
        yf_period = "2y" if range_str in ("1m", "3m", "6m", "1y") else "5y"
        try:
            df_yf = await asyncio.to_thread(_fetch_yf_candles_sync, yf_sym, period=yf_period)
            if df_yf is not None and not df_yf.empty:
                await validate_and_upsert_raw_candles(db, clean_sym, exchange, df_yf)
                # Re-query
                ph_res = await db.execute(
                    select(PriceHistory)
                    .where(
                        PriceHistory.symbol == clean_sym,
                        PriceHistory.date >= start_date
                    )
                    .order_by(asc(PriceHistory.date))
                )
                cached_candles = ph_res.scalars().all()
        except Exception as exc:
            last_fetch_error = exc
            logger.warning("[PriceHistory] Fallback to yfinance failed for %s: %s", clean_sym, exc)

    if not cached_candles:
        if last_fetch_error is not None:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch market history from yfinance for {clean_sym}: {str(last_fetch_error)}"
            )
        return {
            "symbol": clean_sym,
            "range": range_str,
            "adjusted": adjusted,
            "candles": [],
            "markers": [],
            "ema20": [],
            "ema50": [],
            "rsi14": [],
            "avg_cost": avg_cost,
            "stop_loss": None,
            "trailing_stop": None,
            "target_1": None,
            "target_2": None,
            "insufficient_history": True,
            "message": "No price history available"
        }

    # Convert to DataFrame for indicator calculations
    records = []
    for c in cached_candles:
        records.append({
            "Date": c.date,
            "Open": c.open,
            "High": c.high,
            "Low": c.low,
            "Close": c.adj_close if (adjusted and c.adj_close is not None) else c.close,
            "RawClose": c.close,
            "AdjClose": c.adj_close,
            "Volume": c.volume or 0
        })

    df = pd.DataFrame(records).set_index("Date").sort_index()
    close_series = df["Close"]

    ema20_series = close_series.ewm(span=20, adjust=False).mean() if len(close_series) >= 20 else pd.Series(index=df.index, dtype=float)
    ema50_series = close_series.ewm(span=min(50, len(close_series)), adjust=False).mean() if len(close_series) >= 10 else pd.Series(index=df.index, dtype=float)
    rsi14_series = compute_wilder_rsi(close_series, period=14) if len(close_series) >= 14 else pd.Series(index=df.index, dtype=float)

    tech = compute_technical_diagnosis(df, avg_buy_price=avg_cost or float(close_series.iloc[-1]))

    # Slice to display range
    cutoff_date = today_date - timedelta(days=days_back)
    sliced_df = df[df.index >= cutoff_date]
    if sliced_df.empty:
        sliced_df = df.tail(15)

    candles = []
    ema20_list = []
    ema50_list = []
    rsi14_list = []

    for d, row in sliced_df.iterrows():
        t_str = str(d)
        candles.append({
            "time": t_str,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": float(row["Volume"])
        })
        if d in ema20_series.index and pd.notna(ema20_series.loc[d]):
            ema20_list.append({"time": t_str, "value": round(float(ema20_series.loc[d]), 2)})
        if d in ema50_series.index and pd.notna(ema50_series.loc[d]):
            ema50_list.append({"time": t_str, "value": round(float(ema50_series.loc[d]), 2)})
        if d in rsi14_series.index and pd.notna(rsi14_series.loc[d]):
            rsi14_list.append({"time": t_str, "value": round(float(rsi14_series.loc[d]), 2)})

    # Fetch Buy & Sell markers from transactions
    markers = []
    if holding:
        txns_res = await db.execute(
            select(Transaction)
            .where(
                Transaction.holding_id == holding.id,
                Transaction.transaction_type.in_([TransactionType.BUY, TransactionType.SELL])
            )
            .order_by(asc(Transaction.transaction_date))
        )
        txns = txns_res.scalars().all()
        for tx in txns:
            tx_date_str = str(tx.transaction_date)
            # Only include markers within the visible candle dates or history
            is_buy = tx.transaction_type == TransactionType.BUY
            markers.append({
                "time": tx_date_str,
                "position": "belowBar" if is_buy else "aboveBar",
                "color": "#10b981" if is_buy else "#ef4444",
                "shape": "arrowUp" if is_buy else "arrowDown",
                "text": f"{'BUY' if is_buy else 'SELL'} {int(tx.quantity) if tx.quantity.is_integer() else tx.quantity} @ ₹{tx.price:.1f}"
            })

    return {
        "symbol": clean_sym,
        "range": range_str,
        "adjusted": adjusted,
        "candles": candles,
        "markers": markers,
        "ema20": ema20_list,
        "ema50": ema50_list,
        "rsi14": rsi14_list,
        "avg_cost": avg_cost,
        "stop_loss": tech.get("stop_loss"),
        "trailing_stop": tech.get("trailing_stop"),
        "target_1": tech.get("target_1"),
        "target_2": tech.get("target_2"),
        "target_1_label": "estimated",
        "target_2_label": "estimated",
        "disclaimer": DISCLAIMER_TEXT,
        "insufficient_history": len(candles) < 10,
        "message": "Fewer than 10 candles in range" if len(candles) < 10 else None
    }


async def compute_portfolio_history_over_time(
    db: AsyncSession,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Builds the daily portfolio value over time:
    (units held on each date x close price),
    excluding days where a holding has no price and marking them.
    """
    # 1. Fetch all holdings and transactions
    holdings_stmt = select(Holding)
    if user_id is not None:
        holdings_stmt = holdings_stmt.where(Holding.user_id == user_id)
    holdings_res = await db.execute(holdings_stmt)
    holdings = holdings_res.scalars().all()

    if not holdings:
        return []

    holding_ids = [h.id for h in holdings]
    holding_map = {h.id: clean_symbol(h.symbol) for h in holdings}
    symbols = list(set(holding_map.values()))

    tx_stmt = (
        select(Transaction)
        .where(Transaction.holding_id.in_(holding_ids))
        .order_by(asc(Transaction.transaction_date))
    )
    tx_res = await db.execute(tx_stmt)
    transactions = tx_res.scalars().all()

    if not transactions:
        return []

    earliest_date = transactions[0].transaction_date
    today_date = datetime.now(IST).date()

    # 2. Pre-fetch all price history for these symbols from earliest_date to today
    ph_res = await db.execute(
        select(PriceHistory.symbol, PriceHistory.date, PriceHistory.close)
        .where(
            PriceHistory.symbol.in_(symbols),
            PriceHistory.date >= earliest_date,
            PriceHistory.date <= today_date
        )
    )
    prices_map: Dict[Tuple[str, date], float] = {}
    for sym, dt, close in ph_res.all():
        prices_map[(clean_symbol(sym), dt)] = close

    # 3. Step day by day through all trading days
    trading_days = get_trading_days(earliest_date, today_date)
    history_points = []

    # Map transactions by date
    tx_by_date: Dict[date, List[Transaction]] = {}
    for tx in transactions:
        tx_by_date.setdefault(tx.transaction_date, []).append(tx)

    units_held: Dict[str, float] = {sym: 0.0 for sym in symbols}
    cumulative_invested: float = 0.0

    for d in trading_days:
        # Apply transactions on or before this day
        if d in tx_by_date:
            for tx in tx_by_date[d]:
                sym = holding_map.get(tx.holding_id)
                if not sym:
                    continue
                if tx.transaction_type == TransactionType.BUY:
                    units_held[sym] += tx.quantity
                    cumulative_invested += (tx.quantity * tx.price)
                elif tx.transaction_type == TransactionType.SELL:
                    units_held[sym] = max(0.0, units_held[sym] - tx.quantity)
                    cumulative_invested = max(0.0, cumulative_invested - (tx.quantity * tx.price))
                elif tx.transaction_type == TransactionType.BONUS:
                    units_held[sym] += tx.quantity

        # Calculate valuation for symbols where units_held > 0
        day_value = 0.0
        priced_count = 0
        unpriced = []

        active_symbols = [s for s, u in units_held.items() if u > 0]
        if not active_symbols:
            continue

        for sym in active_symbols:
            u = units_held[sym]
            price = prices_map.get((sym, d))
            if price is not None and price > 0:
                day_value += (u * price)
                priced_count += 1
            else:
                # Exclude day's value for this unpriced holding and mark it
                unpriced.append(sym)

        pnl = round(day_value - cumulative_invested, 2)
        history_points.append({
            "date": str(d),
            "invested": round(cumulative_invested, 2),
            "current_value": round(day_value, 2),
            "pnl": pnl,
            "priced_count": priced_count,
            "total_active_holdings": len(active_symbols),
            "unpriced_holdings": unpriced,
            "has_unpriced": len(unpriced) > 0
        })

    return history_points


async def export_price_history_stream(
    db: AsyncSession,
    symbol: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    format_type: str = "csv"
) -> Tuple[io.BytesIO, str, str]:
    """
    Streams price history for a symbol without saving files on disk.
    Supported formats: csv, xlsx, parquet.
    Returns: (buffer: io.BytesIO, media_type: str, filename: str)
    """
    clean_sym = clean_symbol(symbol)
    query = select(PriceHistory).where(PriceHistory.symbol == clean_sym)

    if from_date:
        query = query.where(PriceHistory.date >= from_date)
    if to_date:
        query = query.where(PriceHistory.date <= to_date)

    query = query.order_by(asc(PriceHistory.date))
    res = await db.execute(query)
    rows = res.scalars().all()

    data = []
    for r in rows:
        data.append({
            "symbol": r.symbol,
            "exchange": r.exchange,
            "date": str(r.date),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "adj_close": r.adj_close,
            "volume": r.volume,
            "source": r.source,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None
        })

    df = pd.DataFrame(data)
    date_suffix = f"{from_date or 'start'}_to_{to_date or 'now'}"
    fmt = format_type.lower().strip()

    buf = io.BytesIO()

    if fmt == "xlsx":
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="PriceHistory")
        buf.seek(0)
        return buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"prices_{clean_sym}_{date_suffix}.xlsx"

    elif fmt == "parquet":
        # Convert date to string or datetime for parquet compatibility
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        df.to_parquet(buf, index=False, engine="pyarrow")
        buf.seek(0)
        return buf, "application/octet-stream", f"prices_{clean_sym}_{date_suffix}.parquet"

    else:
        # CSV default
        csv_str = df.to_csv(index=False)
        buf.write(csv_str.encode("utf-8"))
        buf.seek(0)
        return buf, "text/csv; charset=utf-8", f"prices_{clean_sym}_{date_suffix}.csv"


async def get_clean_adjusted_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Optional[AsyncSession] = None
) -> pd.DataFrame:
    """
    Research Hook (Walk-Forward Evaluation).
    Returns a clean, corporate-adjusted OHLCV DataFrame per symbol with:
    - Monotonic DatetimeIndex
    - Adjusted Open, High, Low, Close, Volume
    - No look-ahead leakage
    """
    clean_sym = clean_symbol(symbol)
    
    if db is not None:
        query = select(PriceHistory).where(
            PriceHistory.symbol == clean_sym,
            PriceHistory.exchange == exchange.upper()
        )
        if start_date:
            query = query.where(PriceHistory.date >= start_date)
        if end_date:
            query = query.where(PriceHistory.date <= end_date)
        query = query.order_by(asc(PriceHistory.date))

        res = await db.execute(query)
        rows = res.scalars().all()

        if rows:
            records = []
            for r in rows:
                # Calculate corporate split/dividend adjustment ratio
                adj_factor = (r.adj_close / r.close) if (r.adj_close and r.close > 0) else 1.0
                records.append({
                    "Date": pd.to_datetime(r.date),
                    "Open": round(r.open * adj_factor, 4),
                    "High": round(r.high * adj_factor, 4),
                    "Low": round(r.low * adj_factor, 4),
                    "Close": round((r.adj_close if r.adj_close else r.close), 4),
                    "Volume": r.volume or 0
                })
            df = pd.DataFrame(records).set_index("Date").sort_index()
            return df

    # Fallback to direct yfinance load if db is None or empty
    yf_sym = yf_symbol(clean_sym, exchange)
    df_yf = await asyncio.to_thread(_fetch_yf_candles_sync, yf_sym, period="5y")
    if df_yf.empty:
        return pd.DataFrame()

    df_clean = pd.DataFrame(index=pd.to_datetime(df_yf.index.date))
    adj_col = df_yf["Adj Close"] if "Adj Close" in df_yf else df_yf["Close"]
    raw_close = df_yf["Close"]
    factor = (adj_col / raw_close).fillna(1.0)

    df_clean["Open"] = (df_yf["Open"] * factor).round(4)
    df_clean["High"] = (df_yf["High"] * factor).round(4)
    df_clean["Low"] = (df_yf["Low"] * factor).round(4)
    df_clean["Close"] = adj_col.round(4)
    df_clean["Volume"] = df_yf["Volume"].fillna(0).astype(int)

    if start_date:
        df_clean = df_clean[df_clean.index >= pd.to_datetime(start_date)]
    if end_date:
        df_clean = df_clean[df_clean.index <= pd.to_datetime(end_date)]

    return df_clean.sort_index()


def get_clean_adjusted_ohlcv_sync(
    symbol: str,
    exchange: str = "NSE",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    engine=None
) -> pd.DataFrame:
    """Synchronous research hook for walk-forward evaluation and offline research."""
    clean_sym = clean_symbol(symbol)
    if engine is not None:
        sql = f"SELECT date, open, high, low, close, adj_close, volume FROM price_history WHERE symbol = '{clean_sym}' AND exchange = '{exchange.upper()}'"
        if start_date:
            sql += f" AND date >= '{start_date}'"
        if end_date:
            sql += f" AND date <= '{end_date}'"
        sql += " ORDER BY date ASC"
        df = pd.read_sql(sql, engine)
        if not df.empty:
            df["Date"] = pd.to_datetime(df["date"])
            adj_factor = (df["adj_close"] / df["close"]).where(df["close"] > 0, 1.0).fillna(1.0)
            df_clean = pd.DataFrame(index=df["Date"])
            df_clean["Open"] = (df["open"] * adj_factor).round(4)
            df_clean["High"] = (df["high"] * adj_factor).round(4)
            df_clean["Low"] = (df["low"] * adj_factor).round(4)
            df_clean["Close"] = df["adj_close"].fillna(df["close"]).round(4)
            df_clean["Volume"] = df["volume"].fillna(0).astype(int)
            return df_clean

    yf_sym = yf_symbol(clean_sym, exchange)
    df_yf = _fetch_yf_candles_sync(yf_sym, period="5y")
    if df_yf.empty:
        return pd.DataFrame()

    df_clean = pd.DataFrame(index=pd.to_datetime(df_yf.index.date))
    adj_col = df_yf["Adj Close"] if "Adj Close" in df_yf else df_yf["Close"]
    raw_close = df_yf["Close"]
    factor = (adj_col / raw_close).fillna(1.0)

    df_clean["Open"] = (df_yf["Open"] * factor).round(4)
    df_clean["High"] = (df_yf["High"] * factor).round(4)
    df_clean["Low"] = (df_yf["Low"] * factor).round(4)
    df_clean["Close"] = adj_col.round(4)
    df_clean["Volume"] = df_yf["Volume"].fillna(0).astype(int)

    if start_date:
        df_clean = df_clean[df_clean.index >= pd.to_datetime(start_date)]
    if end_date:
        df_clean = df_clean[df_clean.index <= pd.to_datetime(end_date)]

    return df_clean.sort_index()



async def get_data_coverage_stats(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Returns coverage statistics per symbol including missing trading days.
    """
    query = (
        select(
            PriceHistory.symbol,
            func.min(PriceHistory.date).label("first_date"),
            func.max(PriceHistory.date).label("last_date"),
            func.count(PriceHistory.id).label("row_count")
        )
        .group_by(PriceHistory.symbol)
        .order_by(PriceHistory.symbol)
    )
    res = await db.execute(query)
    coverage_rows = res.all()

    # Pre-fetch all dates for all symbols to count missing trading days
    all_dates_query = select(PriceHistory.symbol, PriceHistory.date)
    all_dates_res = await db.execute(all_dates_query)
    symbol_dates_map: Dict[str, Set[date]] = {}
    for sym, d in all_dates_res.all():
        symbol_dates_map.setdefault(sym, set()).add(d)

    result = []
    for sym, first_d, last_d, count in coverage_rows:
        present = symbol_dates_map.get(sym, set())
        missing = get_missing_trading_days(present, first_d, last_d) if first_d and last_d else []
        result.append({
            "symbol": sym,
            "first_date": str(first_d) if first_d else None,
            "last_date": str(last_d) if last_d else None,
            "row_count": count,
            "missing_trading_days": len(missing)
        })

    return result


async def get_data_issues_list(
    db: AsyncSession,
    symbol: Optional[str] = None,
    unresolved_only: bool = True,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Fetches data quality issues recorded in data_issues table.
    """
    query = select(DataIssue)
    if symbol:
        query = query.where(DataIssue.symbol == clean_symbol(symbol))
    if unresolved_only:
        query = query.where(DataIssue.resolved.is_(False))

    query = query.order_by(desc(DataIssue.created_at)).limit(limit)
    res = await db.execute(query)
    issues = res.scalars().all()

    return [
        {
            "id": iss.id,
            "symbol": iss.symbol,
            "exchange": iss.exchange,
            "date": str(iss.date),
            "issue_type": iss.issue_type,
            "details": iss.details,
            "severity": iss.severity,
            "resolved": iss.resolved,
            "created_at": iss.created_at.isoformat() if iss.created_at else None
        }
        for iss in issues
    ]
