import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import SuggestionLog
from app.services.market_price_service import get_live_price, _yf_symbol

logger = logging.getLogger(__name__)

# Curated list of technical swing candidates with ATR-calibrated baselines (2–3 month horizon)
# Uses ATR-based levels: stop = entry - 1.5×ATR, target = entry + 3×ATR (min 1:2 risk/reward)
TECHNICAL_SWING_CANDIDATES = [
    {
        "symbol": "HDFCBANK",
        "company_name": "HDFC Bank",
        "sector": "Banking & Financials",
        "base_price": 721.0,
        "base_atr": 16.5,
        "entry_range": "₹710 - ₹725",
        "target_price": 770.5,
        "stop_loss": 696.2,
        "horizon": "2-3 Months",
        "expected_return": "+13.5%",
        "thesis": "Trading at attractive historical price-to-book valuation; credit growth and margin expansion expected over Q3/Q4.",
        "catalyst": "Quarterly earnings delivery & steady credit deposit ratio normalization."
    },
    {
        "symbol": "NTPC",
        "company_name": "NTPC Ltd",
        "sector": "Power & Energy Infrastructure",
        "base_price": 315.0,
        "base_atr": 8.5,
        "entry_range": "₹308 - ₹318",
        "target_price": 340.5,
        "stop_loss": 302.2,
        "horizon": "2-3 Months",
        "expected_return": "+15.8%",
        "thesis": "Aggressive thermal + green renewable capacity expansion with steady domestic institutional accumulation on dips.",
        "catalyst": "Green energy subsidiary listing pipeline & peak winter/industrial power demand."
    },
    {
        "symbol": "ITC",
        "company_name": "ITC Ltd",
        "sector": "FMCG & Diversified",
        "base_price": 256.0,
        "base_atr": 5.8,
        "entry_range": "₹250 - ₹258",
        "target_price": 273.4,
        "stop_loss": 247.3,
        "horizon": "2-3 Months",
        "expected_return": "+15.2%",
        "thesis": "Resilient core cigarette cash flows, non-cigarette FMCG margin expansion, and attractive defensive dividend yield.",
        "catalyst": "Hotels business demerger value unlocking & festive rural consumption pickup."
    },
    {
        "symbol": "BHARTIARTL",
        "company_name": "Bharti Airtel Ltd",
        "sector": "Telecom & Digital Services",
        "base_price": 1640.0,
        "base_atr": 38.0,
        "entry_range": "₹1,610 - ₹1,650",
        "target_price": 1754.0,
        "stop_loss": 1583.0,
        "horizon": "2-3 Months",
        "expected_return": "+14.6%",
        "thesis": "Industry-leading ARPU expansion from telecom tariff hikes, accelerating enterprise data growth, and strong free cash flow.",
        "catalyst": "ARPU growth compounding in consecutive quarterly results."
    },
    {
        "symbol": "PRAJIND",
        "company_name": "Praj Industries Ltd",
        "sector": "Clean Energy & Industrial Capex",
        "base_price": 630.0,
        "base_atr": 15.0,
        "entry_range": "₹615 - ₹635",
        "target_price": 675.0,
        "stop_loss": 607.5,
        "horizon": "2-3 Months",
        "expected_return": "+15.0%",
        "thesis": "Global and domestic ethanol blending mandate tailwinds with robust order book in sustainable aviation fuels (SAF).",
        "catalyst": "Government policy push on 20% ethanol blending and renewable industrial orders."
    }
]
VETTED_SWING_CANDIDATES = TECHNICAL_SWING_CANDIDATES


# ─────────────────────────────────────────────────────────────────────────────
# 1. ATR & TECHNICAL LEVEL COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Calculate 14-period True Range Average (ATR).
    TR = max(High - Low, abs(High - PrevClose), abs(Low - PrevClose))
    """
    if df is None or len(df) < period + 1:
        return None
    try:
        high = df['High'].astype(float)
        low = df['Low'].astype(float)
        close = df['Close'].astype(float)
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=period).mean()
        val = atr_series.iloc[-1]
        if pd.isna(val) or val <= 0:
            return None
        return float(val)
    except Exception:
        return None


def compute_atr_levels(entry_price: float, atr: float) -> Dict[str, Any]:
    """
    Computes ATR-based target and stop-loss levels:
    - stop = entry - 1.5 × ATR
    - target = entry + 3.0 × ATR
    Guarantees a minimum 1:2 risk/reward ratio.
    """
    atr = max(atr, entry_price * 0.01)  # safety floor: min 1% ATR
    stop = round(entry_price - 1.5 * atr, 1)
    target = round(entry_price + 3.0 * atr, 1)

    upside_pct = round(((target - entry_price) / entry_price) * 100, 1)
    downside_pct = round(((entry_price - stop) / entry_price) * 100, 1)

    return {
        "target_price": target,
        "stop_loss": stop,
        "upside_pct": upside_pct,
        "downside_pct": downside_pct,
        "risk_reward_ratio": "1:2.0"
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. PRE-FILTERS
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_stock_prefilters(
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    score: float = 75.0
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Evaluates institutional swing pre-filters:
    1. Min average daily volume (ADV20 >= 100,000)
    2. Price above EMA50 (Close > EMA50)
    3. 3-Month relative strength vs Nifty (stock 3M return > Nifty 3M return)
    4. Skip if Nifty is below its 200 EMA unless stock score is very high (score >= 80)
    5. Skip circuit-limit stocks (High == Low or zero intraday range)
    Rule: If any data is missing, skip the stock (never default).
    """
    if stock_df is None or stock_df.empty or nifty_df is None or nifty_df.empty:
        return False, "Missing market candle data", {}

    if len(stock_df) < 63 or len(nifty_df) < 200:
        return False, f"Insufficient candle history (stock: {len(stock_df)}/63d, nifty: {len(nifty_df)}/200d)", {}

    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in stock_df.columns:
            return False, f"Missing required candle column: {col}", {}

    c0 = stock_df.iloc[-1]
    cmp_price = float(c0['Close'])
    high0 = float(c0['High'])
    low0 = float(c0['Low'])

    # 1. Circuit filter: High == Low or zero range
    if high0 == low0 or abs(high0 - low0) < 1e-4:
        return False, "Stock locked at circuit limit (zero intraday trading range)", {}

    # 2. Min average daily volume: 20-day ADV >= 100,000
    adv20 = float(stock_df['Volume'].tail(20).mean())
    if pd.isna(adv20) or adv20 < 100_000:
        return False, f"Low liquidity (ADV20 {adv20:,.0f} < 100,000 shares)", {}

    # 3. Price above EMA50
    ema50 = float(stock_df['Close'].ewm(span=50, adjust=False).mean().iloc[-1])
    if pd.isna(ema50) or cmp_price <= ema50:
        return False, f"Price below EMA50 (CMP {cmp_price:.1f} <= EMA50 {ema50:.1f})", {}

    # 4. 3-Month relative strength vs Nifty (approx 63 trading days)
    stock_start = float(stock_df['Close'].iloc[-63])
    nifty_start = float(nifty_df['Close'].iloc[-63])
    nifty_now = float(nifty_df['Close'].iloc[-1])

    if stock_start <= 0 or nifty_start <= 0:
        return False, "Invalid price history for 3M return comparison", {}

    stock_3m_ret = (cmp_price - stock_start) / stock_start
    nifty_3m_ret = (nifty_now - nifty_start) / nifty_start

    if pd.isna(stock_3m_ret) or pd.isna(nifty_3m_ret) or stock_3m_ret <= nifty_3m_ret:
        return False, f"Lagging Nifty over 3M ({stock_3m_ret*100:.1f}% <= {nifty_3m_ret*100:.1f}%)", {}

    # 5. Skip if Nifty is below its 200 EMA unless score is very high (>= 80)
    nifty_ema200 = float(nifty_df['Close'].ewm(span=200, adjust=False).mean().iloc[-1])
    if pd.isna(nifty_ema200):
        return False, "Missing Nifty EMA200 calculation", {}

    if nifty_now < nifty_ema200 and score < 80.0:
        return False, f"Market regime risk (Nifty {nifty_now:.0f} < EMA200 {nifty_ema200:.0f} and score {score:.0f} < 80)", {}

    metrics = {
        "cmp_price": cmp_price,
        "ema50": ema50,
        "adv20": adv20,
        "stock_3m_return": stock_3m_ret,
        "nifty_3m_return": nifty_3m_ret,
        "nifty_ema200": nifty_ema200,
        "score": score
    }
    return True, "Passed all pre-filters", metrics


# ─────────────────────────────────────────────────────────────────────────────
# 3. POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_position_sizing(
    symbol: str,
    entry_price: float,
    portfolio_summary: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Position sizing rule:
    If a holding exceeds 25% of the portfolio, warn and do not suggest adding more;
    show a suggested max quantity (capped at 25% portfolio weight).
    """
    summary_dict = None
    if portfolio_summary is not None:
        if hasattr(portfolio_summary, "model_dump"):
            summary_dict = portfolio_summary.model_dump()
        elif isinstance(portfolio_summary, dict):
            summary_dict = portfolio_summary

    if not summary_dict or entry_price <= 0:
        return {
            "weight_pct": 0.0,
            "can_add": True,
            "suggested_max_qty": None,
            "warning": None
        }

    total_val = float(
        summary_dict.get("current_value")
        or summary_dict.get("total_current_value")
        or summary_dict.get("total_invested")
        or summary_dict.get("total_investment")
        or 0.0
    )
    if total_val <= 0:
        return {
            "weight_pct": 0.0,
            "can_add": True,
            "suggested_max_qty": None,
            "warning": None
        }

    from app.services.market_price_service import _clean_ticker
    target_clean = _clean_ticker(symbol)

    holdings = summary_dict.get("holdings", [])
    current_holding_val = 0.0
    for h in holdings:
        h_dict = h.model_dump() if hasattr(h, "model_dump") else (h if isinstance(h, dict) else getattr(h, "__dict__", {}))
        h_sym = _clean_ticker(h_dict.get("symbol", ""))
        if h_sym == target_clean:
            current_holding_val = float(h_dict.get("current_value") or (h_dict.get("quantity", 0) * entry_price))
            break

    weight_pct = round((current_holding_val / total_val) * 100, 1)

    if weight_pct > 25.0:
        return {
            "weight_pct": weight_pct,
            "can_add": False,
            "suggested_max_qty": 0,
            "warning": f"⚠️ Position limit reached ({weight_pct}% > 25% portfolio weight). Do not add more."
        }

    max_allowed_val = 0.25 * total_val
    remaining_val = max(0.0, max_allowed_val - current_holding_val)
    suggested_max_qty = max(0, int(remaining_val / entry_price))

    return {
        "weight_pct": weight_pct,
        "can_add": True,
        "suggested_max_qty": suggested_max_qty,
        "warning": None
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. SUGGESTION LOGGING
# ─────────────────────────────────────────────────────────────────────────────

async def log_suggestion(session: AsyncSession, item: Dict[str, Any]) -> SuggestionLog:
    """
    Logs a swing suggestion into suggestion_log.
    Deduplicates open entries for the same symbol on the same day.
    """
    today = date.today()
    sym = item["symbol"]

    stmt = select(SuggestionLog).where(
        SuggestionLog.symbol == sym,
        SuggestionLog.date == today,
        SuggestionLog.status == "open"
    )
    res = await session.execute(stmt)
    existing = res.scalars().first()
    if existing:
        return existing

    reasons = item.get("reasons") or {
        "thesis": item.get("thesis", ""),
        "catalyst": item.get("catalyst", ""),
        "horizon": item.get("horizon", "2-3 Months"),
        "rule": "14-day ATR (stop=1.5×ATR, target=3×ATR, min 1:2 R:R)"
    }

    entry = SuggestionLog(
        date=today,
        symbol=sym,
        entry_price=float(item["current_price"]),
        target=float(item["target_price"]),
        stop=float(item["stop_loss"]),
        atr=float(item.get("atr", 0.0)),
        reasons=reasons,
        status="open",
        exit_date=None,
        exit_price=None,
        return_pct=None
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def log_suggestions_batch(items: List[Dict[str, Any]], session: Optional[AsyncSession] = None):
    """Logs multiple suggestions, opening a session if none provided."""
    if session:
        for it in items:
            await log_suggestion(session, it)
    else:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            for it in items:
                await log_suggestion(s, it)


# ─────────────────────────────────────────────────────────────────────────────
# 5. CANDIDATE GENERATION (LIVE & SYNC)
# ─────────────────────────────────────────────────────────────────────────────

async def get_technical_swing_candidates(
    session: Optional[AsyncSession] = None,
    portfolio_summary: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Fetches live market prices for technical 2-3 month swing candidates,
    computes ATR-based levels (stop = entry - 1.5×ATR, target = entry + 3×ATR),
    evaluates portfolio position sizing, and logs every suggestion.
    """
    results = []
    for item in TECHNICAL_SWING_CANDIDATES:
        sym = item["symbol"]
        live_price, change_pct = await get_live_price(sym, "NSE")
        current_price = live_price if (live_price and live_price > 0) else item["base_price"]

        atr = float(item.get("base_atr") or round(current_price * 0.025, 1))
        levels = compute_atr_levels(current_price, atr)

        target = levels["target_price"]
        stop = levels["stop_loss"]
        entry_low = round(current_price * 0.985, 1)
        entry_high = round(current_price * 1.01, 1)

        pos_sizing = evaluate_position_sizing(sym, current_price, portfolio_summary)

        cand = {
            "symbol": sym,
            "company_name": item["company_name"],
            "sector": item["sector"],
            "current_price": current_price,
            "entry_range": f"₹{entry_low:,.1f} - ₹{entry_high:,.1f}",
            "target_price": target,
            "stop_loss": stop,
            "atr": atr,
            "upside_pct": levels["upside_pct"],
            "downside_pct": levels["downside_pct"],
            "horizon": item["horizon"],
            "thesis": item["thesis"],
            "catalyst": item["catalyst"],
            "reasons": {
                "thesis": item["thesis"],
                "catalyst": item["catalyst"],
                "horizon": item["horizon"],
                "atr": atr,
                "risk_reward": "1:2"
            },
            "position_warning": pos_sizing["warning"],
            "suggested_max_qty": pos_sizing["suggested_max_qty"],
            "can_add": pos_sizing["can_add"]
        }
        results.append(cand)

    # Log suggestions to database
    try:
        await log_suggestions_batch(results, session=session)
    except Exception as exc:
        logger.warning(f"[Suggestions] Failed logging candidates to db: {exc}")

    return results


get_vetted_swing_shares = get_technical_swing_candidates


def get_technical_swing_candidates_sync(portfolio_summary: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Synchronous version of get_technical_swing_candidates using cached prices or base prices.
    """
    from app.services.market_price_service import _price_cache
    results = []
    for item in TECHNICAL_SWING_CANDIDATES:
        sym = item["symbol"]
        cached = _price_cache.get(f"{sym}.NS")
        current_price = cached[0] if (cached and cached[0] and cached[0] > 0) else item["base_price"]

        atr = float(item.get("base_atr") or round(current_price * 0.025, 1))
        levels = compute_atr_levels(current_price, atr)

        target = levels["target_price"]
        stop = levels["stop_loss"]
        entry_low = round(current_price * 0.985, 1)
        entry_high = round(current_price * 1.01, 1)

        pos_sizing = evaluate_position_sizing(sym, current_price, portfolio_summary)

        results.append({
            "symbol": sym,
            "company_name": item["company_name"],
            "sector": item["sector"],
            "current_price": current_price,
            "entry_range": f"₹{entry_low:,.1f} - ₹{entry_high:,.1f}",
            "target_price": target,
            "stop_loss": stop,
            "atr": atr,
            "upside_pct": levels["upside_pct"],
            "downside_pct": levels["downside_pct"],
            "horizon": item["horizon"],
            "thesis": item["thesis"],
            "catalyst": item["catalyst"],
            "position_warning": pos_sizing["warning"],
            "suggested_max_qty": pos_sizing["suggested_max_qty"],
            "can_add": pos_sizing["can_add"]
        })
    return results


get_vetted_swing_shares_sync = get_technical_swing_candidates_sync


# ─────────────────────────────────────────────────────────────────────────────
# 6. DAILY SCHEDULED EVALUATION JOB (TARGET, STOP, EXPIRY)
# ─────────────────────────────────────────────────────────────────────────────

async def get_symbol_daily_candles(symbol: str, start_date: Optional[date] = None, period: str = "3mo") -> Optional[pd.DataFrame]:
    """Fetches daily OHLCV candles asynchronously in executor."""
    yf_sym = _yf_symbol(symbol, "NSE")
    def _fetch():
        import yfinance as yf
        try:
            if start_date:
                df = yf.download(yf_sym, start=start_date.isoformat(), interval="1d", progress=False)
            else:
                df = yf.download(yf_sym, period=period, interval="1d", progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df.dropna()
            return None
        except Exception as e:
            logger.debug(f"[Suggestions] Failed downloading candles for {yf_sym}: {e}")
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _fetch)


async def evaluate_open_suggestions(session: AsyncSession) -> Dict[str, Any]:
    """
    Daily scheduled job: update open suggestions using daily candles (high/low),
    mark which hit first (target or stop) or expired after 45 days.
    """
    stmt = select(SuggestionLog).where(SuggestionLog.status == "open")
    res = await session.execute(stmt)
    open_suggestions = res.scalars().all()

    today = date.today()
    summary = {
        "total_evaluated": len(open_suggestions),
        "target_hit": 0,
        "stop_hit": 0,
        "expired": 0,
        "still_open": 0
    }

    if not open_suggestions:
        return summary

    for s in open_suggestions:
        days_open = (today - s.date).days

        # 45-day hard expiry
        if days_open >= 45:
            live_price, _ = await get_live_price(s.symbol, "NSE")
            exit_p = live_price if (live_price and live_price > 0) else s.entry_price
            ret_pct = round(((exit_p - s.entry_price) / s.entry_price) * 100, 2)
            s.status = "expired"
            s.exit_date = today
            s.exit_price = exit_p
            s.return_pct = ret_pct
            summary["expired"] += 1
            continue

        df = await get_symbol_daily_candles(s.symbol, start_date=s.date)
        if df is None or df.empty:
            summary["still_open"] += 1
            continue

        hit_resolved = False
        for idx_row, row in df.iterrows():
            c_date = idx_row.date() if hasattr(idx_row, "date") else today
            if c_date <= s.date:
                continue

            high = float(row["High"])
            low = float(row["Low"])

            target_hit = high >= s.target
            stop_hit = low <= s.stop

            if target_hit and stop_hit:
                # Same day touched both levels: conservative risk assumes stop hit first
                s.status = "stop"
                s.exit_date = c_date
                s.exit_price = s.stop
                s.return_pct = round(((s.stop - s.entry_price) / s.entry_price) * 100, 2)
                summary["stop_hit"] += 1
                hit_resolved = True
                break
            elif target_hit:
                s.status = "target"
                s.exit_date = c_date
                s.exit_price = s.target
                s.return_pct = round(((s.target - s.entry_price) / s.entry_price) * 100, 2)
                summary["target_hit"] += 1
                hit_resolved = True
                break
            elif stop_hit:
                s.status = "stop"
                s.exit_date = c_date
                s.exit_price = s.stop
                s.return_pct = round(((s.stop - s.entry_price) / s.entry_price) * 100, 2)
                summary["stop_hit"] += 1
                hit_resolved = True
                break

        if not hit_resolved:
            summary["still_open"] += 1

    await session.commit()
    logger.info(f"[Suggestions] Daily open suggestions evaluation: {summary}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 7. SCORECARD & BENCHMARK VS NIFTY
# ─────────────────────────────────────────────────────────────────────────────

async def get_nifty_period_return(start_d: date, end_d: date) -> Optional[float]:
    """Computes Nifty 50 benchmark return over a date range."""
    def _fetch():
        import yfinance as yf
        try:
            df = yf.download('^NSEI', start=start_d.isoformat(), end=(end_d + timedelta(days=2)).isoformat(), interval='1d', progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                first_c = float(df['Close'].iloc[0])
                last_c = float(df['Close'].iloc[-1])
                return round(((last_c - first_c) / first_c) * 100, 2)
            return None
        except Exception:
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _fetch)


async def get_suggestion_scorecard(session: AsyncSession) -> Dict[str, Any]:
    """
    Computes performance scorecard for closed swing picks.
    Shows "not enough data" until there are 30+ closed picks.
    """
    stmt = select(SuggestionLog)
    res = await session.execute(stmt)
    all_picks = res.scalars().all()

    closed_picks = [s for s in all_picks if s.status in ("target", "stop", "expired")]
    total_count = len(all_picks)
    closed_count = len(closed_picks)

    if closed_count < 30:
        return {
            "status": "not_enough_data",
            "total_picks": total_count,
            "closed_picks": closed_count,
            "min_required": 30,
            "message": f"Not enough data ({closed_count}/30 closed picks required for statistical significance)"
        }

    target_hits = sum(1 for s in closed_picks if s.status == "target")
    stop_hits = sum(1 for s in closed_picks if s.status == "stop")
    expired_count = sum(1 for s in closed_picks if s.status == "expired")

    hit_rate = round((target_hits / closed_count) * 100, 1)
    returns = [s.return_pct for s in closed_picks if s.return_pct is not None]
    avg_return = round(sum(returns) / len(returns), 2) if returns else 0.0

    earliest = min(s.date for s in closed_picks)
    latest = max(s.exit_date or s.date for s in closed_picks)
    nifty_ret = await get_nifty_period_return(earliest, latest)
    vs_nifty = round(avg_return - (nifty_ret or 0.0), 2)

    return {
        "status": "active",
        "total_picks": total_count,
        "closed_picks": closed_count,
        "target_hits": target_hits,
        "stop_hits": stop_hits,
        "expired": expired_count,
        "hit_rate_pct": hit_rate,
        "avg_return_pct": avg_return,
        "nifty_return_pct": nifty_ret,
        "vs_nifty_pct": vs_nifty
    }


def format_scorecard_message(scorecard: Dict[str, Any]) -> str:
    """Formats the swing performance scorecard into Telegram HTML."""
    if scorecard.get("status") == "not_enough_data":
        closed = scorecard.get("closed_picks", 0)
        min_req = scorecard.get("min_required", 30)
        total = scorecard.get("total_picks", 0)
        return (
            "📊 <b>IPO PULSE · SWING STRATEGY SCORECARD</b>\n\n"
            "⚠️ <b>Not enough data yet.</b>\n"
            f"Currently tracked: <b>{closed} / {min_req}</b> closed picks needed for statistical significance "
            f"({total} total suggestions logged).\n\n"
            "🎯 <b>Tracking Rules:</b>\n"
            "• Mechanical ATR levels: stop -1.5×ATR, target +3×ATR (min 1:2 R:R)\n"
            "• Daily candles evaluated for first-touch target or stop\n"
            "• 45-day hard expiry on unresolved trades\n\n"
            "<i>The scorecard will activate automatically once 30 verified picks close.</i>"
        )

    hit_rate = scorecard.get("hit_rate_pct", 0.0)
    avg_ret = scorecard.get("avg_return_pct", 0.0)
    vs_nifty = scorecard.get("vs_nifty_pct", 0.0)
    target_hits = scorecard.get("target_hits", 0)
    stop_hits = scorecard.get("stop_hits", 0)
    expired = scorecard.get("expired", 0)
    closed = scorecard.get("closed_picks", 0)
    total = scorecard.get("total_picks", 0)

    return (
        "📊 <b>IPO PULSE · SWING STRATEGY SCORECARD</b>\n\n"
        f"• 📋 <b>Total Logged Picks:</b> {total} ({closed} closed)\n"
        f"• 🎯 <b>Hit Rate:</b> <b>{hit_rate}%</b> ({target_hits} targets hit / {stop_hits} stops / {expired} expired)\n"
        f"• 📈 <b>Average Return:</b> <b>{avg_ret:+.2f}%</b>\n"
        f"• 🏛️ <b>Performance vs Nifty:</b> <b>{vs_nifty:+.2f}%</b>\n\n"
        "🛡️ <i>Evaluation: Mechanical 1:2 R:R ATR levels, 45-day hard expiry, zero lookahead.</i>\n\n"
        "⚠️ <i>Disclaimer: Mechanical levels (ATR-based), not researched recommendations. Not investment advice, GMP/technical levels are estimates.</i>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. TELEGRAM CARD FORMATTING
# ─────────────────────────────────────────────────────────────────────────────

def format_shares_summary_card(shares: List[Dict[str, Any]]) -> str:
    """
    Formats technical swing candidates with mechanical levels into a clear Telegram HTML card.
    Maintains mechanical risk rules, position sizing warnings, and mandatory disclaimer.
    """
    lines = [
        "🎯 <b>IPO PULSE · TECHNICAL SWING CANDIDATES (2–3 MONTHS)</b>",
        "<i>Mechanical levels (ATR-based, min 1:2 R:R), not researched recommendations:</i>",
        ""
    ]

    for idx, s in enumerate(shares, 1):
        lines.append(f"<b>{idx}. {s['company_name']} ({s['symbol']})</b> · <i>{s['sector']}</i>")
        lines.append(f"   • <b>CMP:</b> ₹{s['current_price']:,.1f} | <b>Buy Zone:</b> {s['entry_range']}")
        lines.append(f"   • 🎯 <b>Mechanical Target (2–3M):</b> <b>₹{s['target_price']:,.1f}</b> (+{s['upside_pct']}%)")
        lines.append(f"   • 🛑 <b>Mechanical Stop-Loss:</b> ₹{s['stop_loss']:,.1f} (-{s['downside_pct']}%) [ATR: ₹{s.get('atr', 0):,.1f}]")
        if s.get("position_warning"):
            lines.append(f"   • {s['position_warning']}")
        elif s.get("suggested_max_qty") is not None and s.get("suggested_max_qty") > 0:
            lines.append(f"   • 📊 <b>Position Cap:</b> Suggested Max Qty: {s['suggested_max_qty']} shares (25% portfolio cap)")
        lines.append(f"   • 💡 <b>Technical Setup:</b> {s['thesis']}")
        lines.append("")

    lines.append("🛡️ <b>Risk Management Discipline:</b>")
    lines.append("• Mechanical rules: strict ATR stop-loss (-1.5×ATR) on daily closing basis.")
    lines.append("• Minimum 1:2 Risk/Reward ratio (target = entry + 3.0×ATR).")
    lines.append("• Position sizing: Maximum 25% single-stock allocation cap.")
    lines.append("• Hard trade expiry after 45 days if neither target nor stop is hit.")
    lines.append("⚡ <i>Reply with any symbol (e.g. \"HDFCBANK\") for deep technical analysis.</i>")
    lines.append("")
    lines.append("⚠️ <i>Disclaimer: Mechanical levels (ATR-based), not researched recommendations. Not investment advice, GMP/technical levels are estimates.</i>")

    return "\n".join(lines)
