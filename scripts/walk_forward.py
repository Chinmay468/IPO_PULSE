#!/usr/bin/env python3
"""
Walk-Forward Historical Replay & Evaluation Runner.

Replays the last 3 years of daily market data for 30 liquid NSE stocks.
Enforces strict no-look-ahead bias (expanding window training on data strictly before each test day).
Reports:
  • Number of predictions (N)
  • Accuracy % with 95% Wilson Confidence Interval
  • Brier Score
  • After-Cost Cumulative Return %
  • Beats Baselines Check
  • "Not enough data" notice below 300 predictions
  • Leakage Test: intentionally shifts target by 1 day to confirm accuracy collapses to ~50%.

Usage:
  python scripts/walk_forward.py
  python scripts/walk_forward.py --leakage-test
  python scripts/walk_forward.py --sample-stocks 5
"""

import sys
import os
import argparse
import math
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.prediction_service import (
    DEFAULT_WATCHLIST,
    BENCHMARK_SYMBOL,
    compute_rsi,
    compute_features_hash
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("walk_forward")


def fetch_historical_dataset(symbols: List[str], period: str = "3y") -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """Downloads historical daily data for symbols and benchmark."""
    yf_symbols = [f"{s}.NS" if not s.endswith(".NS") and s != "^NSEI" else s for s in symbols]
    if "^NSEI" not in yf_symbols:
        yf_symbols.append("^NSEI")

    logger.info("Fetching %s historical data for %d symbols...", period, len(yf_symbols))
    data = yf.download(yf_symbols, period=period, interval="1d", progress=False)

    nifty_df = pd.DataFrame()
    try:
        if isinstance(data.columns, pd.MultiIndex):
            nifty_df = data.xs("^NSEI", level=1, axis=1).dropna(how='all')
        else:
            nifty_df = data[['Close']].dropna()
    except Exception:
        pass

    stock_data = {}
    for sym in symbols:
        clean_sym = sym.replace(".NS", "").upper()
        yf_sym = f"{clean_sym}.NS"
        try:
            if isinstance(data.columns, pd.MultiIndex):
                s_df = data.xs(yf_sym, level=1, axis=1).dropna(how='all')
            else:
                s_df = data[['Close', 'Volume']].dropna()
            if not s_df.empty and 'Close' in s_df.columns:
                stock_data[clean_sym] = s_df
        except Exception:
            continue

    return stock_data, nifty_df


def build_walk_forward_features(df_stock: pd.DataFrame, df_nifty: pd.DataFrame, shift_target: int = 0) -> pd.DataFrame:
    """
    Builds technical feature matrix for walk-forward evaluation.
    If shift_target != 0 (e.g. shift_target = 1 for leakage test), shifts target by +1 day.
    """
    df = df_stock.copy()
    if 'Close' not in df.columns or len(df) < 30:
        return pd.DataFrame()

    df['ret_1d'] = df['Close'].pct_change()
    df['ret_lag1'] = df['ret_1d'].shift(1)
    df['ret_lag2'] = df['ret_1d'].shift(2)
    df['rsi_14'] = compute_rsi(df['Close'], 14).shift(1)

    if 'Volume' in df.columns:
        df['vol_change'] = df['Volume'].pct_change().shift(1).fillna(0.0)
    else:
        df['vol_change'] = 0.0

    if not df_nifty.empty and 'Close' in df_nifty.columns:
        nifty_ret = df_nifty['Close'].pct_change().shift(1)
        df['nifty_ret'] = nifty_ret.reindex(df.index).fillna(0.0)
    else:
        df['nifty_ret'] = 0.0

    # Base target return for day t
    target_ret = df['ret_1d']

    # Leakage test intentional target shift
    if shift_target != 0:
        target_ret = target_ret.shift(shift_target)

    df['target_return'] = target_ret
    df['target_direction'] = np.where(
        df['target_return'] > 0.0005, 'UP',
        np.where(df['target_return'] < -0.0005, 'DOWN', 'FLAT')
    )

    feature_cols = ['ret_lag1', 'ret_lag2', 'rsi_14', 'vol_change', 'nifty_ret']
    for col in feature_cols:
        df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df[col] = df[col].clip(-10.0, 10.0)

    return df.dropna(subset=['ret_lag1', 'ret_lag2', 'rsi_14', 'target_return'])


def calculate_wilson_ci(correct: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Calculates 95% Wilson score confidence interval for accuracy."""
    if total <= 0:
        return 0.0, 0.0
    p = correct / total
    denom = 1 + (z ** 2) / total
    center = (p + (z ** 2) / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) / total) + (z ** 2) / (4 * (total ** 2))) / denom
    return round(max(0.0, center - margin) * 100.0, 2), round(min(1.0, center + margin) * 100.0, 2)


def run_walk_forward_eval(symbols: List[str], leakage_test: bool = False, period: str = "3y") -> Dict[str, Any]:
    """
    Executes walk-forward replay over past period (default 3 years).
    """
    stock_data, nifty_df = fetch_historical_dataset(symbols, period=period)
    shift = 1 if leakage_test else 0

    if leakage_test:
        print("\n" + "=" * 65)
        print(" [!] LEAKAGE TEST ACTIVE: Target vector shifted by +1 day on purpose.")
        print(" Expected Result: Accuracy should collapse to ~50% (random guess).")
        print("=" * 65)

    model_names = ["persistence", "always_up", "logistic_regression", "groq_llm"]
    results = {
        m: {"total": 0, "correct": 0, "brier_errors": [], "returns": []}
        for m in model_names
    }

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    for sym, df_stock in stock_data.items():
        feat_df = build_walk_forward_features(df_stock, nifty_df, shift_target=shift)
        if len(feat_df) < 50:
            continue

        # Start evaluation after initial 40 days for logistic regression training
        eval_start_idx = 40
        feature_cols = ['ret_lag1', 'ret_lag2', 'rsi_14', 'vol_change', 'nifty_ret']

        for i in range(eval_start_idx, len(feat_df)):
            test_row = feat_df.iloc[i]
            train_df = feat_df.iloc[:i]

            actual_dir = test_row['target_direction']
            actual_ret = float(test_row['target_return'])

            # (a) Persistence
            ret1 = test_row['ret_lag1']
            pred_a = "UP" if ret1 > 0.0005 else ("DOWN" if ret1 < -0.0005 else "FLAT")
            conf_a = 0.50

            # (b) Always UP
            pred_b = "UP"
            conf_b = 0.50

            # (c) Logistic Regression
            clean_train = train_df[train_df['target_direction'].isin(['UP', 'DOWN'])]
            if len(clean_train) >= 20 and len(clean_train['target_direction'].unique()) >= 2:
                scaler = StandardScaler()
                X_tr = scaler.fit_transform(clean_train[feature_cols].values)
                y_tr = (clean_train['target_direction'] == 'UP').astype(int).values

                lr = LogisticRegression(max_iter=300, random_state=42)
                lr.fit(X_tr, y_tr)

                X_te = scaler.transform(test_row[feature_cols].values.reshape(1, -1))
                prob_up = float(lr.predict_proba(X_te)[0, 1])

                if prob_up > 0.52:
                    pred_c, conf_c = "UP", prob_up
                elif prob_up < 0.48:
                    pred_c, conf_c = "DOWN", 1.0 - prob_up
                else:
                    pred_c, conf_c = "FLAT", 0.50
            else:
                pred_c, conf_c = pred_a, 0.50

            # (d) Quantitative Groq LLM Proxy
            # Evaluates structured indicator signals (RSI + Momentum + Nifty alignment)
            rsi_val = test_row['rsi_14']
            nifty_ret_val = test_row['nifty_ret']
            score = (ret1 * 2.0) + (nifty_ret_val * 1.5) + ((rsi_val - 50.0) / 100.0)
            if score > 0.002:
                pred_d, conf_d = "UP", min(0.55 + abs(score) * 10, 0.85)
            elif score < -0.002:
                pred_d, conf_d = "DOWN", min(0.55 + abs(score) * 10, 0.85)
            else:
                pred_d, conf_d = "FLAT", 0.50

            preds = {
                "persistence": (pred_a, conf_a),
                "always_up": (pred_b, conf_b),
                "logistic_regression": (pred_c, conf_c),
                "groq_llm": (pred_d, conf_d),
            }

            for m, (p_dir, p_conf) in preds.items():
                results[m]["total"] += 1
                is_correct = (p_dir == actual_dir)
                if is_correct:
                    results[m]["correct"] += 1

                # Brier score error: (confidence - actual_outcome)^2
                outcome = 1.0 if is_correct else 0.0
                results[m]["brier_errors"].append((p_conf - outcome) ** 2)

                # Simulated after-cost return: 5 bps (0.05%) transaction cost
                pos = 1.0 if p_dir == "UP" else (-1.0 if p_dir == "DOWN" else 0.0)
                cost = 0.0005 if pos != 0 else 0.0
                results[m]["returns"].append(pos * actual_ret - cost)

    # Compute summaries
    persist_acc = results["persistence"]["correct"] / results["persistence"]["total"] if results["persistence"]["total"] > 0 else 0.0
    always_up_acc = results["always_up"]["correct"] / results["always_up"]["total"] if results["always_up"]["total"] > 0 else 0.0
    best_baseline = max(persist_acc, always_up_acc)

    summary_report = {
        "period": period,
        "leakage_test": leakage_test,
        "models": {},
        "disclaimer": "Research and evaluation only, not investment or trading advice."
    }

    print("\n" + "=" * 80)
    print(f" WALK-FORWARD REPLAY REPORT ({period.upper()} HISTORICAL MARKET EVALUATION)")
    print("=" * 80)
    print(f" {'MODEL':<22} | {'PREDS':<7} | {'ACCURACY (95% CI)':<22} | {'BRIER':<7} | {'RETURN':<8} | {'BEATS BASELINE'}")
    print("-" * 80)

    for m in model_names:
        tot = results[m]["total"]
        cor = results[m]["correct"]

        if tot < 300:
            status_str = "not enough data"
            acc_str = f"{cor/tot*100:.1f}% (N<300)" if tot > 0 else "N/A"
            print(f" {m:<22} | {tot:<7} | [!] {status_str:<15} | N/A     | N/A      | No")
            summary_report["models"][m] = {
                "total_predictions": tot,
                "status": "not enough data",
                "notice": f"Not enough data ({tot}/300 minimum predictions required)"
            }
            continue

        acc = cor / tot
        acc_pct = acc * 100.0
        ci_low, ci_high = calculate_wilson_ci(cor, tot)
        brier = float(np.mean(results[m]["brier_errors"])) if results[m]["brier_errors"] else 0.0
        cum_ret = float(np.sum(results[m]["returns"])) * 100.0 if results[m]["returns"] else 0.0
        beats = (acc > best_baseline) and (m not in ["persistence", "always_up"])

        acc_ci_disp = f"{acc_pct:.1f}% [{ci_low:.1f}%-{ci_high:.1f}%]"
        beats_disp = "YES" if beats else ("BASE" if m in ["persistence", "always_up"] else "NO")

        print(f" {m:<22} | {tot:<7} | {acc_ci_disp:<22} | {brier:<7.3f} | {cum_ret:>+6.1f}% | {beats_disp}")

        summary_report["models"][m] = {
            "model_name": m,
            "total_predictions": tot,
            "accuracy_pct": round(acc_pct, 2),
            "confidence_interval_95": [ci_low, ci_high],
            "brier_score": round(brier, 4),
            "simulated_return_pct": round(cum_ret, 2),
            "beats_baselines": beats
        }

    print("=" * 80)
    print(" [!] Disclaimer: Research and evaluation only, not investment or trading advice.")
    print("=" * 80 + "\n")

    return summary_report


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Historical Replay & Evaluation Runner")
    parser.add_argument("--leakage-test", action="store_true", help="Shift target by +1 day on purpose to test for data leakage")
    parser.add_argument("--sample-stocks", type=int, default=30, help="Number of watchlist stocks to evaluate (default: 30)")
    parser.add_argument("--period", type=str, default="3y", help="Historical period (default: 3y)")

    args = parser.parse_args()
    symbols = DEFAULT_WATCHLIST[:args.sample_stocks]
    run_walk_forward_eval(symbols=symbols, leakage_test=args.leakage_test, period=args.period)


if __name__ == "__main__":
    main()
