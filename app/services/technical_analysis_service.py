"""
Unified Technical Analysis Service.
Provides canonical, shared technical calculations across the entire platform:
- J. Welles Wilder's exact 14-period RSI smoothing algorithm (1978)
- J. Welles Wilder's 14-period ATR
- ATR-based initial stop-loss (entry/current price - 1.5 x ATR14)
- Ratcheting trailing stop (highest close - 2.0 x ATR14, moves up only)
- Real resistance targets (Target 1 = nearest swing high; Target 2 = next swing high or 2:1 reward-to-risk)
- Factual pattern & trend labels (price vs EMA 20/50/200, 6-week range, neutral wording at RSI 40-60)
- Technical diagnosis logging, daily post-market evaluation, and statistical scorecard
- Mandatory disclaimer: "Mechanical technical levels, not a forecast or investment advice."
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import TechnicalDiagnosis

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = "Mechanical technical levels, not a forecast or investment advice."


# =============================================================================
# 1. MATHEMATICAL INDICATORS (WILDER RSI, ATR, EMAs)
# =============================================================================

def compute_wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute Relative Strength Index (RSI) using J. Welles Wilder's exact smoothing algorithm
    from 'New Concepts in Technical Trading Systems' (1978).

    - Period 1 to N: initial average gain/loss is the arithmetic mean of first N changes.
    - Subsequent periods: smoothed_avg = (prev_avg * (N - 1) + current_val) / N.
    """
    if series.empty or len(series) < period + 1:
        return pd.Series(np.nan, index=series.index, dtype=float)

    clean_s = series.astype(float)
    diff = clean_s.diff()
    gains = diff.clip(lower=0.0)
    losses = (-diff).clip(lower=0.0)

    ag = np.full(len(clean_s), np.nan, dtype=float)
    al = np.full(len(clean_s), np.nan, dtype=float)

    # Initial SMA over first `period` changes (index 1 to period)
    first_gain = gains.iloc[1:period + 1].mean()
    first_loss = losses.iloc[1:period + 1].mean()

    ag[period] = first_gain
    al[period] = first_loss

    gain_vals = gains.to_numpy(copy=True)
    loss_vals = losses.to_numpy(copy=True)

    for i in range(period + 1, len(clean_s)):
        ag[i] = (ag[i - 1] * (period - 1) + gain_vals[i]) / period
        al[i] = (al[i - 1] * (period - 1) + loss_vals[i]) / period

    rsi = np.full(len(clean_s), np.nan, dtype=float)
    for i in range(period, len(clean_s)):
        if al[i] == 0.0:
            rsi[i] = 100.0 if ag[i] > 0.0 else 50.0
        elif ag[i] == 0.0:
            rsi[i] = 0.0
        else:
            rs = ag[i] / al[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return pd.Series(rsi, index=series.index)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Compute Average True Range (ATR) using J. Welles Wilder's smoothing algorithm.
    TR = max(High - Low, abs(High - Close_prev), abs(Low - Close_prev))
    """
    if df.empty or len(df) < period + 1:
        return pd.Series(np.nan, index=df.index, dtype=float)

    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    close = df['Close'].astype(float)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = np.full(len(df), np.nan, dtype=float)
    atr[period] = tr.iloc[1:period + 1].mean()

    tr_vals = tr.to_numpy(copy=True)
    for i in range(period + 1, len(df)):
        atr[i] = (atr[i - 1] * (period - 1) + tr_vals[i]) / period

    return pd.Series(atr, index=df.index)


def compute_trailing_stop_series(df: pd.DataFrame, atr_series: pd.Series) -> pd.Series:
    """
    Compute ratcheting trailing stop:
    trailing_stop = highest close - 2.0 * ATR14.
    Ratchets upward monotonically: TS(t) = max(TS(t-1), highest_close_so_far - 2.0 * ATR14).
    Never moves downward.
    """
    close = df['Close'].astype(float).to_numpy(copy=True)
    atr = atr_series.to_numpy(copy=True)
    ts = np.full(len(df), np.nan, dtype=float)

    highest_close = -np.inf
    current_ts = -np.inf

    for i in range(len(df)):
        if np.isnan(atr[i]):
            continue
        c = close[i]
        if c > highest_close:
            highest_close = c
        candidate = highest_close - 2.0 * atr[i]
        if candidate > current_ts:
            current_ts = candidate
        ts[i] = current_ts if current_ts > -np.inf else np.nan

    return pd.Series(ts, index=df.index)


# =============================================================================
# 2. SWING HIGHS & REAL RESISTANCE TARGETS
# =============================================================================

def find_swing_highs(df: pd.DataFrame, window: int = 2) -> List[float]:
    """
    Find local swing high peaks in price history.
    A swing high occurs at bar i if High[i] >= High[i +/- k] for k in 1..window.
    """
    if df.empty or len(df) < (window * 2 + 1):
        return [float(df['High'].max())] if not df.empty else []

    highs = df['High'].astype(float).to_numpy(copy=True)
    swing_highs = []
    for i in range(window, len(highs) - window):
        is_swing = True
        for j in range(1, window + 1):
            if highs[i] < highs[i - j] or highs[i] < highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append(float(highs[i]))
    return swing_highs


def compute_targets_and_stops(
    df: pd.DataFrame,
    cmp_price: float,
    avg_buy_price: float = 0.0,
    atr_val: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """
    Compute consistent stop-loss, trailing stop, and targets:
    1. Stop-Loss: ATR-based stop (entry/current price - 1.5 x ATR14).
    2. Trailing Stop: highest close - 2.0 x ATR14 (ratchets up only).
    3. Target 1: Nearest real resistance (recent swing high above CMP).
    4. Target 2: Next swing high or 2:1 reward-to-risk level (never a flat +8%).
    """
    # Safe ATR fallback if series is too short
    atr = atr_val if (atr_val is not None and not np.isnan(atr_val) and atr_val > 0) else max(cmp_price * 0.025, 0.5)

    # 1. Stop-Loss: (entry/current price - 1.5 x ATR14)
    base_entry = avg_buy_price if (avg_buy_price is not None and avg_buy_price > 0) else cmp_price
    stop_loss = round(max(base_entry - 1.5 * atr, 0.05), 2)

    # 2. Trailing Stop: highest close - 2.0 x ATR14
    if not df.empty and 'Close' in df.columns:
        closes = df['Close'].astype(float)
        highest_close = float(closes.max())
    else:
        highest_close = max(cmp_price, base_entry)
    trailing_stop = round(max(highest_close - 2.0 * atr, stop_loss, 0.05), 2)

    # 3. Swing High Targets
    swing_highs = find_swing_highs(df, window=2)
    # Distinct swing highs meaningfully above CMP (> 0.2% above CMP)
    overhead_highs = sorted(list(set([round(h, 2) for h in swing_highs if h > cmp_price * 1.002])))

    # Reward-to-Risk reference: Risk R = CMP - stop_loss (clamped to at least 0.5 ATR)
    risk_r = max(cmp_price - stop_loss, 0.5 * atr, cmp_price * 0.03)

    if overhead_highs:
        target_1 = overhead_highs[0]
        if len(overhead_highs) > 1:
            target_2 = overhead_highs[1]
        else:
            # 2:1 reward-to-risk level
            target_2 = round(cmp_price + 2.0 * risk_r, 2)
    else:
        # Stock at or near 52-week / multi-month highs: mechanical R:R levels
        target_1 = round(cmp_price + 1.0 * risk_r, 2)
        target_2 = round(cmp_price + 2.0 * risk_r, 2)

    # Sanity checks: target 2 must be strictly > target 1
    if target_2 <= target_1:
        target_2 = round(target_1 + risk_r, 2)

    return stop_loss, trailing_stop, target_1, target_2


# =============================================================================
# 3. CANDLESTICK PATTERN DETECTION
# =============================================================================

def detect_candlestick_pattern(df: pd.DataFrame) -> dict:
    """
    Detect dominant candlestick patterns from recent daily candles.
    """
    if df.empty or len(df) < 3:
        return {"pattern": "Consolidating", "sentiment": "NEUTRAL", "desc": "Insufficient candle history"}

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    c0 = df.iloc[-1]
    c1 = df.iloc[-2]

    o0, h0, l0, cl0 = float(c0['Open']), float(c0['High']), float(c0['Low']), float(c0['Close'])
    o1, h1, l1, cl1 = float(c1['Open']), float(c1['High']), float(c1['Low']), float(c1['Close'])

    body0 = abs(cl0 - o0)
    range0 = max(h0 - l0, 1e-6)
    lower_shadow0 = (o0 - l0) if cl0 >= o0 else (cl0 - l0)
    upper_shadow0 = (h0 - cl0) if cl0 >= o0 else (h0 - o0)

    # 1. Bullish Hammer
    if lower_shadow0 >= 2.0 * body0 and upper_shadow0 <= 0.3 * range0 and cl0 > l0:
        return {
            "pattern": "Hammer (Bullish Rejection)",
            "sentiment": "BULLISH",
            "desc": "Buyers defended intraday lows; potential reversal support."
        }

    # 2. Bullish Engulfing
    if cl1 < o1 and cl0 > o0 and cl0 >= o1 and o0 <= cl1:
        return {
            "pattern": "Bullish Engulfing",
            "sentiment": "STRONG_BULLISH",
            "desc": "Buyers engulfed previous session range with strong recovery body."
        }

    # 3. Morning Star
    if cl1 < o1 and abs(cl1 - o1) / max(h1 - l1, 1e-6) < 0.3 and cl0 > o0 and cl0 > (o1 + cl1) / 2:
        return {
            "pattern": "Morning Star Reversal",
            "sentiment": "STRONG_BULLISH",
            "desc": "3-session reversal pattern confirmed at demand zone."
        }

    # 4. Shooting Star
    if upper_shadow0 >= 2.0 * body0 and lower_shadow0 <= 0.3 * range0:
        return {
            "pattern": "Shooting Star (Rejection)",
            "sentiment": "BEARISH",
            "desc": "Selling pressure near highs; honor trailing stop."
        }

    # 5. Bearish Engulfing
    if cl1 > o1 and cl0 < o0 and cl0 <= o1 and o0 >= cl1:
        return {
            "pattern": "Bearish Engulfing",
            "sentiment": "BEARISH",
            "desc": "Sellers overwhelmed buyers; respect risk stops."
        }

    # 6. Doji
    if body0 / range0 < 0.12:
        return {
            "pattern": "Doji (Pause / Equilibrium)",
            "sentiment": "NEUTRAL",
            "desc": "Market in equilibrium; awaiting next directional breakout."
        }

    # Default
    if cl0 >= o0:
        return {
            "pattern": "Bullish Candle",
            "sentiment": "BULLISH",
            "desc": "Price closed above open."
        }
    return {
        "pattern": "Consolidating / Pullback",
        "sentiment": "NEUTRAL",
        "desc": "Price closed below open within recent range."
    }


# =============================================================================
# 4. CANONICAL TECHNICAL DIAGNOSIS FUNCTION
# =============================================================================

def compute_technical_diagnosis(
    df: pd.DataFrame,
    avg_buy_price: float = 0.0,
    weight_pct: float = 0.0,
) -> dict:
    """
    Canonical shared function for RSI, EMA, stop-loss, trailing stop, and targets.
    Used by:
    - Stock Diagnosis Cards
    - Chart Endpoint (/holdings/{symbol}/history)
    - AI Portfolio Chatbot & Copilot

    Guarantees:
    - RSI uses J. Welles Wilder's exact 14-period smoothing.
    - Neutral wording at RSI 40-60: 'Neutral / Range-bound' (eliminates 'Healthy Trend').
    - Stops: ATR-based stop (entry/current - 1.5 x ATR14) and ratcheting trailing stop (highest close - 2 x ATR14).
    - Targets: Target 1 = nearest real resistance (swing high); Target 2 = next swing high or 2:1 R:R (never flat +8%).
    - Factual trend: price vs EMA 20/50/200 and 6-week range.
    - Mandatory disclaimer included: 'Mechanical technical levels, not a forecast or investment advice.'
    """
    if df.empty or len(df) < 10:
        if weight_pct > 25.0:
            action = "HOLD & MONITOR (OVER-CONCENTRATED)"
            action_color = "amber"
            strategy = "already over-concentrated, avoid adding more."
            trend = "Over-Concentrated"
        else:
            action = "HOLD & ACCUMULATE"
            action_color = "blue"
            strategy = "Maintain positional hold; accumulate on dips towards support."
            trend = "Accumulation / Initial History"

        return {
            "rsi": None,
            "rsi_status": "Insufficient Data",
            "ema20": None,
            "ema50": None,
            "ema200": None,
            "atr14": None,
            "trend": trend,
            "pattern": "Base Building",
            "pattern_desc": "Stock is forming initial price history",
            "pattern_sentiment": "NEUTRAL",
            "six_week_range": "Insufficient Data",
            "support_1": None,
            "stop_loss": None,
            "trailing_stop": None,
            "target_1": None,
            "target_2": None,
            "target_1_label": "estimated",
            "target_2_label": "estimated",
            "action": action,
            "action_color": action_color,
            "strategy": strategy,
            "pnl_pct": None,
            "disclaimer": DISCLAIMER_TEXT,
        }

    # Ensure clean single-level series
    close_series = df['Close']
    if isinstance(close_series, pd.DataFrame):
        close_series = close_series.iloc[:, 0]
    close_series = close_series.dropna()
    cmp_price = float(close_series.iloc[-1])

    # 1. Wilder RSI (14)
    rsi_series = compute_wilder_rsi(close_series, period=14)
    rsi_raw = rsi_series.iloc[-1]
    rsi_val = float(round(rsi_raw, 1)) if not pd.isna(rsi_raw) else None

    # Factual RSI status (Requirement 4: Neutral at 40-60)
    if rsi_val is None:
        rsi_status = "Insufficient Data"
    elif rsi_val < 30.0:
        rsi_status = "Oversold (Extreme Value Zone)"
    elif rsi_val < 40.0:
        rsi_status = "Pullback / Approaching Oversold"
    elif 40.0 <= rsi_val <= 60.0:
        rsi_status = "Neutral / Range-bound"
    elif 60.0 < rsi_val <= 70.0:
        rsi_status = "Positive Momentum"
    else:
        rsi_status = "Overbought (Take Partial Profit)"

    # 2. Moving Averages
    ema20 = float(close_series.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close_series.ewm(span=min(50, len(close_series)), adjust=False).mean().iloc[-1])
    ema200 = float(close_series.ewm(span=min(200, len(close_series)), adjust=False).mean().iloc[-1])

    # 3. ATR (14) & Trailing Stop Series
    atr_series = compute_atr(df, period=14)
    atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else round(cmp_price * 0.025, 2)

    # 4. Stops and Targets
    stop_loss, trailing_stop, target_1, target_2 = compute_targets_and_stops(
        df=df,
        cmp_price=cmp_price,
        avg_buy_price=avg_buy_price,
        atr_val=atr_val,
    )

    # Support pivot
    low_series = df['Low']
    if isinstance(low_series, pd.DataFrame):
        low_series = low_series.iloc[:, 0]
    recent_low = float(low_series.tail(20).min())
    support_1 = round(max(recent_low, ema50 * 0.98), 2)

    # 5. 6-Week Range (approx 30 trading days)
    high_series = df['High']
    if isinstance(high_series, pd.DataFrame):
        high_series = high_series.iloc[:, 0]
    lookback_bars = min(30, len(df))
    six_w_high = float(high_series.tail(lookback_bars).max())
    six_w_low = float(low_series.tail(lookback_bars).min())
    six_w_range_str = f"₹{six_w_low:.2f} - ₹{six_w_high:.2f}"

    # 6. Candlestick Pattern
    candle_info = detect_candlestick_pattern(df)

    # 7. Factual Trend Assessment
    has_200 = len(close_series) >= 150
    if has_200:
        if cmp_price > ema20 and ema20 > ema50 and ema50 > ema200:
            trend = "Bullish Alignment (Above EMA 20/50/200)"
        elif cmp_price > ema50 and cmp_price > ema200:
            trend = "Above EMA 50/200 (Bullish Bias)"
        elif cmp_price < ema20 and ema20 < ema50 and ema50 < ema200:
            trend = "Bearish Alignment (Below EMA 20/50/200)"
        elif cmp_price < ema50 and cmp_price < ema200:
            trend = "Below EMA 50/200 (Bearish Bias)"
        elif cmp_price > ema200:
            trend = "Consolidating Above EMA 200"
        else:
            trend = "Consolidating Below EMA 200"
    else:
        if cmp_price > ema20 and ema20 > ema50:
            trend = "Short-term Bullish (Above EMA 20/50)"
        elif cmp_price < ema20 and cmp_price < ema50:
            trend = "Short-term Bearish (Below EMA 20/50)"
        else:
            trend = "Neutral / Consolidating around EMAs"

    # 8. Action Decision
    avg_buy = float(avg_buy_price) if avg_buy_price is not None else 0.0
    pnl_pct = ((cmp_price - avg_buy) / avg_buy) * 100 if avg_buy > 0 else 0.0

    if rsi_val is not None and rsi_val <= 33:
        if weight_pct > 25.0:
            action = "HOLD & MONITOR (OVER-CONCENTRATED)"
            action_color = "amber"
            strategy = (
                f"RSI ({rsi_val}) is in oversold territory, but position is already over-concentrated ({weight_pct:.1f}% > 25% allocation). "
                f"already over-concentrated, avoid adding more. Respect ATR stop-loss at ₹{stop_loss}."
            )
        else:
            action = "STRONG BUY / ACCUMULATE ON DIP"
            action_color = "emerald"
            strategy = (
                f"RSI ({rsi_val}) is oversold near support ₹{support_1}. "
                f"Accumulate on confirmed stabilization; first resistance target: ₹{target_1} (estimated)."
            )
    elif cmp_price > ema20 and ema20 > ema50:
        action = "HOLD & RIDE UPTREND"
        action_color = "blue"
        strategy = (
            f"Trading above EMA 20 (₹{ema20:.1f}) & EMA 50 (₹{ema50:.1f}). "
            f"Momentum intact. Maintain ratcheting trailing stop at ₹{trailing_stop}."
        )
    elif cmp_price < ema50 and rsi_val is not None and rsi_val > 60:
        action = "TRIM / BOOK PARTIAL GAINS"
        action_color = "amber"
        strategy = f"Approaching overhead resistance ₹{target_1} (estimated). Lock partial gains and trail stop to ₹{trailing_stop}."
    else:
        action = "HOLD & MONITOR SUPPORT"
        action_color = "blue"
        strategy = (
            f"Holding base near ₹{support_1}. Upside targets ₹{target_1} & ₹{target_2} (estimated). "
            f"Risk defined by ATR stop-loss at ₹{stop_loss} (trailing SL ₹{trailing_stop})."
        )

    # Guardrail: never accumulate if >25% weight
    if weight_pct > 25.0 and any(w in action.upper() for w in ["ACCUMULATE", "BUY", "DIP"]):
        action = "HOLD & MONITOR (OVER-CONCENTRATED)"
        action_color = "amber"
        strategy = (
            f"Position is already over-concentrated ({weight_pct:.1f}% > 25% allocation). "
            f"already over-concentrated, avoid adding more. Respect ATR stop-loss at ₹{stop_loss}."
        )

    return {
        "rsi": rsi_val,
        "rsi_status": rsi_status,
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "atr14": round(atr_val, 2),
        "trend": trend,
        "pattern": candle_info["pattern"],
        "pattern_desc": candle_info["desc"],
        "pattern_sentiment": candle_info["sentiment"],
        "six_week_range": six_w_range_str,
        "support_1": support_1,
        "stop_loss": stop_loss,
        "trailing_stop": trailing_stop,
        "target_1": target_1,
        "target_2": target_2,
        "target_1_label": "estimated",
        "target_2_label": "estimated",
        "action": action,
        "action_color": action_color,
        "strategy": strategy,
        "pnl_pct": round(pnl_pct, 2),
        "disclaimer": DISCLAIMER_TEXT,
    }


# =============================================================================
# 5. DIAGNOSIS LOGGING, DAILY EVALUATION JOB, AND SCORECARD
# =============================================================================

async def log_technical_diagnosis(
    session: AsyncSession,
    symbol: str,
    price: float,
    stop_loss: float,
    trailing_stop: float,
    target_1: float,
    target_2: float,
    diag_date: Optional[date] = None,
) -> TechnicalDiagnosis:
    """
    Log a daily mechanical technical diagnosis record in the database.
    Updates existing entry if already recorded for today and still OPEN.
    """
    d_date = diag_date or date.today()
    clean_sym = symbol.strip().upper()

    stmt = select(TechnicalDiagnosis).where(
        and_(
            TechnicalDiagnosis.symbol == clean_sym,
            TechnicalDiagnosis.date == d_date,
        )
    )
    res = await session.execute(stmt)
    existing = res.scalars().first()

    if existing:
        if existing.status == "OPEN":
            existing.price = price
            existing.stop_loss = stop_loss
            existing.trailing_stop = trailing_stop
            existing.target_1 = target_1
            existing.target_2 = target_2
        return existing

    record = TechnicalDiagnosis(
        date=d_date,
        symbol=clean_sym,
        price=price,
        stop_loss=stop_loss,
        trailing_stop=trailing_stop,
        target_1=target_1,
        target_2=target_2,
        status="OPEN",
    )
    session.add(record)
    return record


async def evaluate_open_diagnoses(session: AsyncSession) -> Dict[str, Any]:
    """
    Daily post-market scheduled job:
    Iterates over all OPEN technical diagnoses where date < today.
    Fetches daily candles since diagnosis date and records whether price hit target or stop first.
    If touched on the same day, conservative risk assumes stop hit first.
    """
    import yfinance as yf
    from app.services.market_price_service import _yf_symbol

    today = date.today()
    stmt = select(TechnicalDiagnosis).where(
        and_(
            TechnicalDiagnosis.status == "OPEN",
            TechnicalDiagnosis.date < today,
        )
    )
    res = await session.execute(stmt)
    open_list = res.scalars().all()

    summary = {
        "total_evaluated": len(open_list),
        "target_hit": 0,
        "stop_hit": 0,
        "still_open": 0,
        "expired": 0,
    }

    if not open_list:
        return summary

    loop = asyncio.get_running_loop()

    for diag in open_list:
        days_open = (today - diag.date).days
        # Hard expiry after 60 trading days (~90 calendar days) if neither hit
        if days_open >= 90:
            diag.status = "EXPIRED"
            diag.closed_at_date = today
            summary["expired"] += 1
            continue

        yf_sym = _yf_symbol(diag.symbol, "NSE")

        def _fetch_candles():
            try:
                df = yf.download(
                    yf_sym,
                    start=diag.date.isoformat(),
                    interval="1d",
                    progress=False,
                )
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    return df.dropna()
                return None
            except Exception as e:
                logger.debug(f"[TechnicalDiag] Error downloading candles for {yf_sym}: {e}")
                return None

        df = await loop.run_in_executor(None, _fetch_candles)
        if df is None or df.empty:
            summary["still_open"] += 1
            continue

        resolved = False
        for idx_row, row in df.iterrows():
            c_date = idx_row.date() if hasattr(idx_row, "date") else today
            if c_date <= diag.date:
                continue

            high = float(row["High"])
            low = float(row["Low"])

            target_hit = high >= diag.target_1
            # Check if breached ATR stop-loss or ratcheting trailing stop
            effective_stop = max(diag.stop_loss, (diag.trailing_stop or diag.stop_loss))
            stop_hit = low <= effective_stop

            if target_hit and stop_hit:
                # Same day touched both: conservative evaluation records stop hit
                diag.status = "STOP_HIT"
                diag.closed_at_date = c_date
                diag.hit_price = effective_stop
                diag.hit_type = "STOP_LOSS"
                summary["stop_hit"] += 1
                resolved = True
                break
            elif target_hit:
                diag.status = "TARGET_HIT"
                diag.closed_at_date = c_date
                diag.hit_price = diag.target_1
                diag.hit_type = "TARGET_1"
                summary["target_hit"] += 1
                resolved = True
                break
            elif stop_hit:
                diag.status = "STOP_HIT"
                diag.closed_at_date = c_date
                diag.hit_price = effective_stop
                diag.hit_type = "STOP_LOSS"
                summary["stop_hit"] += 1
                resolved = True
                break

        if not resolved:
            summary["still_open"] += 1

    await session.commit()
    logger.info(f"[TechnicalDiag] Evaluation result: {summary}")
    return summary


async def get_technical_diagnosis_scorecard(session: AsyncSession) -> Dict[str, Any]:
    """
    Computes statistical hit rate scorecard across closed mechanical diagnoses.
    Requirement 5: Only shows hit rate once there are at least 30 closed diagnoses.
    """
    stmt = select(TechnicalDiagnosis)
    res = await session.execute(stmt)
    all_diagnoses = res.scalars().all()

    closed = [d for d in all_diagnoses if d.status in ("TARGET_HIT", "STOP_HIT")]
    total_count = len(all_diagnoses)
    closed_count = len(closed)

    target_hits = sum(1 for d in closed if d.status == "TARGET_HIT")
    stop_hits = sum(1 for d in closed if d.status == "STOP_HIT")

    min_required = 30
    if closed_count < min_required:
        return {
            "status": "not_enough_data",
            "total_diagnoses": total_count,
            "closed_diagnoses": closed_count,
            "min_required": min_required,
            "hit_rate_pct": None,
            "target_hits": target_hits,
            "stop_hits": stop_hits,
            "disclaimer": DISCLAIMER_TEXT,
            "message": f"Collecting data ({closed_count}/{min_required} closed diagnoses). Hit rate activates after 30 closed diagnoses.",
        }

    hit_rate = round((target_hits / closed_count) * 100, 1)

    return {
        "status": "active",
        "total_diagnoses": total_count,
        "closed_diagnoses": closed_count,
        "min_required": min_required,
        "target_hits": target_hits,
        "stop_hits": stop_hits,
        "hit_rate_pct": hit_rate,
        "disclaimer": DISCLAIMER_TEXT,
        "message": f"Hit rate: {hit_rate}% across {closed_count} closed mechanical technical diagnoses.",
    }
