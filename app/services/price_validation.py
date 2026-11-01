"""
Price Data Validation Engine.
Enforces data integrity, flags anomalies (>40% jumps, trading gaps),
and rejects corrupted OHLCV candles (high < low, close out of bounds, zero/null prices).
"""

import math
from datetime import date
from typing import List, Dict, Any, Tuple, Optional
from app.services.nse_holidays import get_trading_days


class ValidationResult:
    def __init__(self, is_valid: bool, issues: List[Dict[str, Any]]):
        self.is_valid = is_valid
        self.issues = issues


def validate_candle(
    symbol: str,
    exchange: str,
    d: date,
    open_val: Optional[float],
    high_val: Optional[float],
    low_val: Optional[float],
    close_val: Optional[float],
    adj_close_val: Optional[float],
    volume_val: Optional[int],
    prev_date: Optional[date] = None,
    prev_close: Optional[float] = None
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Validates a single daily candle.
    Returns:
        (is_valid: bool, issues: list of issue dicts to record in data_issues)
    If is_valid is False, the candle MUST NOT be inserted into price_history.
    """
    issues = []
    is_valid = True

    # 1. Null or non-positive price check
    for name, val in [("open", open_val), ("high", high_val), ("low", low_val), ("close", close_val)]:
        if val is None or math.isnan(val) or val <= 0:
            issues.append({
                "symbol": symbol,
                "exchange": exchange,
                "date": d,
                "issue_type": "NULL_OR_ZERO_PRICE",
                "details": f"{name.upper()} price is invalid: {val}",
                "severity": "ERROR",
                "resolved": False
            })
            is_valid = False

    if not is_valid:
        return False, issues

    # 2. High < Low check
    if high_val < low_val:
        issues.append({
            "symbol": symbol,
            "exchange": exchange,
            "date": d,
            "issue_type": "HIGH_LESS_THAN_LOW",
            "details": f"High ({high_val}) is strictly less than Low ({low_val})",
            "severity": "ERROR",
            "resolved": False
        })
        is_valid = False

    # 3. Close outside [Low, High] check
    epsilon = 1e-4
    if close_val < (low_val - epsilon) or close_val > (high_val + epsilon):
        issues.append({
            "symbol": symbol,
            "exchange": exchange,
            "date": d,
            "issue_type": "CLOSE_OUT_OF_BOUNDS",
            "details": f"Close ({close_val}) is outside range [{low_val}, {high_val}]",
            "severity": "ERROR",
            "resolved": False
        })
        is_valid = False

    if not is_valid:
        return False, issues

    # 4. Check for single-day change exceeding 40% (Flag for review, keep candle)
    if prev_close is not None and prev_close > 0:
        change_pct = abs(close_val - prev_close) / prev_close
        if change_pct > 0.40:
            issues.append({
                "symbol": symbol,
                "exchange": exchange,
                "date": d,
                "issue_type": "LARGE_PRICE_JUMP",
                "details": (
                    f"Single-day price change of {change_pct * 100:.1f}% "
                    f"(from {prev_close} to {close_val}). Flagged for review (possible unadjusted split/bonus)."
                ),
                "severity": "REVIEW",
                "resolved": False
            })

    # 5. Check for gap of more than one trading day
    if prev_date is not None:
        next_day = prev_date + type(prev_date).resolution
        if d > next_day:
            missing_between = get_trading_days(prev_date + type(prev_date).resolution, d - type(d).resolution)
            if len(missing_between) > 1:
                issues.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "date": d,
                    "issue_type": "TRADING_GAP",
                    "details": (
                        f"Gap of {len(missing_between)} missing trading days between {prev_date} and {d}: "
                        f"{', '.join(str(m) for m in missing_between[:5])}"
                        + (f" and {len(missing_between) - 5} more" if len(missing_between) > 5 else "")
                    ),
                    "severity": "WARNING",
                    "resolved": False
                })

    return True, issues
