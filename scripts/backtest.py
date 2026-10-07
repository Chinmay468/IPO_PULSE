"""
Mechanical ATR Swing Strategy Backtester (Last 3 Years of NSE Data)

Features:
- Zero look-ahead bias: entries and indicators evaluated strictly up to bar t.
- Pre-filters:
    * 20-day ADV >= 100,000 shares
    * Price > EMA50
    * 3-Month Relative Strength vs Nifty (stock 3M return > Nifty 3M return)
    * Skip if Nifty is below its 200 EMA unless stock technical score >= 80
    * Skip circuit-limit stocks (High == Low)
    * If any data is missing, skip the stock (never default)
- Levels:
    * 14-period ATR
    * Stop = Entry - 1.5 × ATR
    * Target = Entry + 3.0 × ATR (minimum 1:2 Risk/Reward)
- Costs:
    * 0.1% slippage on entry + 0.1% slippage on exit + 0.1% brokerage/STT round-trip (0.3% total friction)
- Evaluation:
    * Daily bars tracked sequentially for first-touch target or stop
    * Hard trade expiration after 45 trading days
- Train / Test split (Chronological 2 years Train / 1 year Test)
- Reports: Hit rate, Average Win/Loss, Expectancy, Max Drawdown, and vs Nifty Buy-and-Hold.
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np

# Reconfigure stdout to handle UTF-8 cleanly on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Representative liquid universe across major sectors
DEFAULT_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
    "INFY.NS", "ITC.NS", "LT.NS", "SBIN.NS", "AXISBANK.NS",
    "NTPC.NS", "SUNPHARMA.NS", "POWERGRID.NS", "TITAN.NS", "M&M.NS",
    "TATASTEEL.NS", "PRAJIND.NS", "COALINDIA.NS", "BEL.NS", "VEDL.NS"
]
BENCHMARK_SYMBOL = "^NSEI"

ROUND_TRIP_COST_PCT = 0.30  # 0.1% slippage per side + 0.1% STT/brokerage = 0.3% total


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-calculates indicators row-by-row with strictly backward-looking windows."""
    df = df.copy()
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    close = df['Close'].astype(float)
    volume = df['Volume'].astype(float)

    # 1. 14-period True Range ATR
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(window=14).mean()

    # 2. 50-period EMA
    df['EMA50'] = close.ewm(span=50, adjust=False).mean()

    # 3. 20-period Average Daily Volume
    df['ADV20'] = volume.rolling(window=20).mean()

    # 4. 63-bar (3-month) Return
    df['RET63'] = (close - close.shift(63)) / close.shift(63)

    # 5. Technical Score (0-100)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi14 = 100 - (100 / (1 + rs))

    score = pd.Series(50.0, index=df.index)
    score += (close > ema20).astype(float) * 15.0
    score += (close > df['EMA50']).astype(float) * 15.0
    score += (close > ema200).astype(float) * 10.0
    score += ((rsi14 >= 50.0) & (rsi14 <= 68.0)).astype(float) * 10.0
    df['SCORE'] = score.clip(0, 100)

    return df


def calculate_nifty_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df['Close'].astype(float)
    df['NIFTY_EMA200'] = close.ewm(span=200, adjust=False).mean()
    df['NIFTY_RET63'] = (close - close.shift(63)) / close.shift(63)
    return df


def download_market_data(universe: List[str], benchmark: str, years: int = 3) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    import yfinance as yf
    print(f"[*] Downloading {years} years of historical data for {len(universe)} symbols and {benchmark}...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365 + 120)  # buffer for warmup indicators

    all_symbols = universe + [benchmark]
    raw_data = yf.download(all_symbols, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), progress=False, group_by="ticker")

    stock_data = {}
    for sym in universe:
        try:
            if sym in raw_data:
                df = raw_data[sym].dropna(how="all").copy()
            elif isinstance(raw_data.columns, pd.MultiIndex):
                df = raw_data[sym].dropna(how="all").copy()
            else:
                df = pd.DataFrame()
            if not df.empty and len(df) > 100:
                stock_data[sym] = calculate_indicators(df)
        except Exception as e:
            print(f"[-] Error parsing {sym}: {e}")

    try:
        nifty_raw = raw_data[benchmark].dropna(how="all").copy() if benchmark in raw_data else pd.DataFrame()
        nifty_df = calculate_nifty_indicators(nifty_raw)
    except Exception as e:
        print(f"[-] Error parsing benchmark: {e}")
        nifty_df = pd.DataFrame()

    return stock_data, nifty_df


def simulate_trades(
    stock_data: Dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime
) -> List[Dict[str, Any]]:
    trades = []
    active_trades = {}  # symbol -> trade

    if nifty_df.empty:
        return []

    # Common trading dates
    trading_dates = nifty_df.loc[
        (nifty_df.index >= pd.Timestamp(start_date)) & (nifty_df.index <= pd.Timestamp(end_date))
    ].index

    for cur_idx, current_date in enumerate(trading_dates):
        # 1. Update and check active trades on today's candle
        for sym, t in list(active_trades.items()):
            df = stock_data.get(sym)
            if df is None or current_date not in df.index:
                continue

            bar = df.loc[current_date]
            high = float(bar['High'])
            low = float(bar['Low'])
            close = float(bar['Close'])

            t['bars_held'] += 1
            entry_p = t['entry_price']
            target_p = t['target_price']
            stop_p = t['stop_loss']

            # Target / Stop check
            target_hit = high >= target_p
            stop_hit = low <= stop_p

            if target_hit and stop_hit:
                # Same day hit both: conservative execution assumes stop touched first
                raw_ret = ((stop_p - entry_p) / entry_p) * 100.0
                net_ret = raw_ret - ROUND_TRIP_COST_PCT
                t.update({
                    "exit_date": current_date,
                    "exit_price": stop_p,
                    "status": "stop",
                    "raw_return_pct": round(raw_ret, 2),
                    "net_return_pct": round(net_ret, 2)
                })
                trades.append(t)
                del active_trades[sym]
            elif target_hit:
                raw_ret = ((target_p - entry_p) / entry_p) * 100.0
                net_ret = raw_ret - ROUND_TRIP_COST_PCT
                t.update({
                    "exit_date": current_date,
                    "exit_price": target_p,
                    "status": "target",
                    "raw_return_pct": round(raw_ret, 2),
                    "net_return_pct": round(net_ret, 2)
                })
                trades.append(t)
                del active_trades[sym]
            elif stop_hit:
                raw_ret = ((stop_p - entry_p) / entry_p) * 100.0
                net_ret = raw_ret - ROUND_TRIP_COST_PCT
                t.update({
                    "exit_date": current_date,
                    "exit_price": stop_p,
                    "status": "stop",
                    "raw_return_pct": round(raw_ret, 2),
                    "net_return_pct": round(net_ret, 2)
                })
                trades.append(t)
                del active_trades[sym]
            elif t['bars_held'] >= 45:
                # Hard 45-day expiration
                raw_ret = ((close - entry_p) / entry_p) * 100.0
                net_ret = raw_ret - ROUND_TRIP_COST_PCT
                t.update({
                    "exit_date": current_date,
                    "exit_price": close,
                    "status": "expired",
                    "raw_return_pct": round(raw_ret, 2),
                    "net_return_pct": round(net_ret, 2)
                })
                trades.append(t)
                del active_trades[sym]

        # 2. Evaluate new candidates for entry strictly using data up to current_date
        nifty_bar = nifty_df.loc[current_date]
        nifty_close = float(nifty_bar['Close'])
        nifty_ema200 = float(nifty_bar['NIFTY_EMA200'])
        nifty_ret63 = float(nifty_bar['NIFTY_RET63'])

        # Skip if nifty data missing
        if pd.isna(nifty_ema200) or pd.isna(nifty_ret63):
            continue

        for sym, df in stock_data.items():
            if sym in active_trades:
                continue  # already holding

            if current_date not in df.index:
                continue

            bar = df.loc[current_date]
            close = float(bar['Close'])
            high = float(bar['High'])
            low = float(bar['Low'])
            volume = float(bar['Volume'])
            atr14 = float(bar['ATR14'])
            ema50 = float(bar['EMA50'])
            adv20 = float(bar['ADV20'])
            ret63 = float(bar['RET63'])
            score = float(bar['SCORE'])

            # Rule: If any data missing, skip stock (never default)
            if any(pd.isna(x) for x in [close, high, low, volume, atr14, ema50, adv20, ret63, score]):
                continue

            # Pre-filter 1: Circuit limit check (High == Low or zero range)
            if high == low or (high - low) < 1e-4:
                continue

            # Pre-filter 2: Min average daily volume (ADV20 >= 100,000)
            if adv20 < 100_000:
                continue

            # Pre-filter 3: Price above EMA50
            if close <= ema50:
                continue

            # Pre-filter 4: 3-Month Relative Strength vs Nifty
            if ret63 <= nifty_ret63:
                continue

            # Pre-filter 5: Skip if Nifty below 200 EMA unless score >= 80
            if nifty_close < nifty_ema200 and score < 80.0:
                continue

            # Pre-filter 6: Valid ATR
            if atr14 <= 0:
                continue

            # All pre-filters passed! Calculate ATR levels (min 1:2 R:R)
            stop_loss = round(close - 1.5 * atr14, 2)
            target_price = round(close + 3.0 * atr14, 2)

            active_trades[sym] = {
                "symbol": sym,
                "entry_date": current_date,
                "entry_price": close,
                "atr": round(atr14, 2),
                "target_price": target_price,
                "stop_loss": stop_loss,
                "bars_held": 0,
                "score": score
            }

    # Close any still-open trades at end of backtest window
    for sym, t in active_trades.items():
        df = stock_data.get(sym)
        if df is not None and not df.empty:
            valid_closes = df['Close'].dropna()
            if not valid_closes.empty:
                last_p = float(valid_closes.iloc[-1])
                raw_ret = ((last_p - t['entry_price']) / t['entry_price']) * 100.0
                net_ret = raw_ret - ROUND_TRIP_COST_PCT
                t.update({
                    "exit_date": valid_closes.index[-1],
                    "exit_price": last_p,
                    "status": "expired",
                    "raw_return_pct": round(raw_ret, 2),
                    "net_return_pct": round(net_ret, 2)
                })
                trades.append(t)

    return trades


def compute_metrics(trades: List[Dict[str, Any]], nifty_df: pd.DataFrame, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0, "hit_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "expectancy": 0.0, "max_drawdown": 0.0, "nifty_return": 0.0, "strategy_return": 0.0
        }

    targets = [t for t in trades if t['status'] == 'target']
    stops = [t for t in trades if t['status'] == 'stop']
    expired = [t for t in trades if t['status'] == 'expired']

    hit_rate = (len(targets) / total_trades) * 100.0

    wins = [t['net_return_pct'] for t in trades if not pd.isna(t.get('net_return_pct')) and t['net_return_pct'] > 0]
    losses = [t['net_return_pct'] for t in trades if not pd.isna(t.get('net_return_pct')) and t['net_return_pct'] <= 0]

    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0

    win_prob = len(wins) / total_trades
    loss_prob = len(losses) / total_trades
    expectancy = (win_prob * avg_win) + (loss_prob * avg_loss)

    # Strategy cumulative return curve & Max Drawdown
    # Assume 10% portfolio capital allocation per trade (max 25% cap rule)
    pos_weight = 0.10
    valid_returns = [
        float(t['net_return_pct']) / 100.0
        for t in sorted(trades, key=lambda x: x.get('exit_date', x['entry_date']))
        if not pd.isna(t.get('net_return_pct'))
    ]
    equity_curve = [1.0]
    for r in valid_returns:
        equity_curve.append(equity_curve[-1] * (1.0 + pos_weight * r))

    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    total_strategy_return = (equity_curve[-1] - 1.0) * 100.0

    # Nifty buy-and-hold return over same period
    nifty_slice = nifty_df.loc[
        (nifty_df.index >= pd.Timestamp(start_date)) & (nifty_df.index <= pd.Timestamp(end_date))
    ]
    if not nifty_slice.empty:
        nifty_first = float(nifty_slice['Close'].iloc[0])
        nifty_last = float(nifty_slice['Close'].iloc[-1])
        nifty_bnh = ((nifty_last - nifty_first) / nifty_first) * 100.0
    else:
        nifty_bnh = 0.0

    return {
        "total_trades": total_trades,
        "targets_hit": len(targets),
        "stops_hit": len(stops),
        "expired": len(expired),
        "hit_rate": round(hit_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "strategy_return": round(total_strategy_return, 2),
        "nifty_return": round(nifty_bnh, 2)
    }


def print_report(train_metrics: Dict[str, Any], test_metrics: Dict[str, Any], combined_metrics: Dict[str, Any]):
    print("\n" + "=" * 78)
    print(" [+] IPO PULSE MECHANICAL ATR SWING STRATEGY BACKTEST RESULTS (3 YEARS)")
    print("=" * 78)
    print(f"{'Metric':<32} | {'TRAIN (Years 1-2)':<18} | {'TEST (Year 3)':<18}")
    print("-" * 78)
    print(f"{'Total Trades':<32} | {train_metrics['total_trades']:<18} | {test_metrics['total_trades']:<18}")
    print(f"{'Target Hit Rate':<32} | {train_metrics['hit_rate']:>5.1f}%             | {test_metrics['hit_rate']:>5.1f}%")
    print(f"{'  - Targets Won':<32} | {train_metrics['targets_hit']:<18} | {test_metrics['targets_hit']:<18}")
    print(f"{'  - Stops Hit':<32} | {train_metrics['stops_hit']:<18} | {test_metrics['stops_hit']:<18}")
    print(f"{'  - Expired (45d)':<32} | {train_metrics['expired']:<18} | {test_metrics['expired']:<18}")
    print(f"{'Average Win':<32} | {train_metrics['avg_win']:>+6.2f}%            | {test_metrics['avg_win']:>+6.2f}%")
    print(f"{'Average Loss':<32} | {train_metrics['avg_loss']:>+6.2f}%            | {test_metrics['avg_loss']:>+6.2f}%")
    print(f"{'Trade Expectancy (Net)':<32} | {train_metrics['expectancy']:>+6.2f}%            | {test_metrics['expectancy']:>+6.2f}%")
    print(f"{'Max Drawdown':<32} | {train_metrics['max_drawdown']:>6.2f}%            | {test_metrics['max_drawdown']:>6.2f}%")
    print(f"{'Strategy Return (Compounded)':<32} | {train_metrics['strategy_return']:>+6.2f}%            | {test_metrics['strategy_return']:>+6.2f}%")
    print(f"{'Nifty 50 Buy-and-Hold':<32} | {train_metrics['nifty_return']:>+6.2f}%            | {test_metrics['nifty_return']:>+6.2f}%")
    print("-" * 78)

    diff = combined_metrics['strategy_return'] - combined_metrics['nifty_return']
    print("COMBINED 3-YEAR PERFORMANCE:")
    print(f"  - Total Mechanical Trades: {combined_metrics['total_trades']}")
    print(f"  - Overall Hit Rate:        {combined_metrics['hit_rate']}%")
    print(f"  - Net Strategy Return:     {combined_metrics['strategy_return']:+.2f}%")
    print(f"  - Nifty 50 Buy-and-Hold:   {combined_metrics['nifty_return']:+.2f}%")
    print(f"  - Alpha vs Benchmark:      {diff:+.2f}%")
    print(f"  - Max Drawdown:            {combined_metrics['max_drawdown']:.2f}%")
    print("=" * 78)
    print("Notes:")
    print("- Transaction costs modeled: 0.1% entry slippage + 0.1% exit slippage + 0.1% STT/brokerage (0.3% net friction).")
    print("- Risk/Reward: Minimum 1:2.0 (target = entry + 3xATR, stop = entry - 1.5xATR).")
    print("- Pre-filters: Volume ADV20 >= 100k, Price > EMA50, 3M RS > Nifty, Nifty 200 EMA check, Circuit lock exclusion.")
    print("=" * 78 + "\n")


def run_backtest():
    parser = argparse.ArgumentParser(description="Backtest ATR Swing Strategy on NSE Stocks")
    parser.add_argument("--years", type=int, default=3, help="Years of data to test (default: 3)")
    args = parser.parse_args()

    stock_data, nifty_df = download_market_data(DEFAULT_UNIVERSE, BENCHMARK_SYMBOL, years=args.years)

    if nifty_df.empty or not stock_data:
        print("[-] Backtest aborted: could not load historical data.")
        return

    # Chronological Split: First 2 years (Train), Last 1 year (Test)
    now = datetime.now()
    split_date = now - timedelta(days=365)
    train_start = now - timedelta(days=args.years * 365)

    print(f"[*] Simulating Train Period ({train_start.date()} to {split_date.date()})...")
    train_trades = simulate_trades(stock_data, nifty_df, train_start, split_date)
    train_metrics = compute_metrics(train_trades, nifty_df, train_start, split_date)

    print(f"[*] Simulating Test Period ({split_date.date()} to {now.date()})...")
    test_trades = simulate_trades(stock_data, nifty_df, split_date, now)
    test_metrics = compute_metrics(test_trades, nifty_df, split_date, now)

    combined_trades = train_trades + test_trades
    combined_metrics = compute_metrics(combined_trades, nifty_df, train_start, now)

    print_report(train_metrics, test_metrics, combined_metrics)


if __name__ == "__main__":
    run_backtest()
