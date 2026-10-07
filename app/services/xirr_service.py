"""
XIRR (Extended Internal Rate of Return) calculation service.
Pure Python implementation using Newton-Raphson with bounded bisection fallback.
Returns annualized percentage (e.g., 10.0 for 10.0% annualized gain).
"""
from datetime import date
from typing import Sequence, Tuple, Optional


def calculate_xirr(
    cashflows: Sequence[Tuple[date, float]],
    guess: float = 0.1,
    max_iter: int = 100,
    tol: float = 1e-6
) -> Optional[float]:
    """
    Computes XIRR as an annualized percentage for a sequence of (date, amount) tuples.

    Convention:
      - Outflows (investments, purchases, SIPs) are NEGATIVE amounts.
      - Inflows (redemptions, dividends received, current portfolio value) are POSITIVE amounts.

    Returns:
      Float percentage rounded to 2 decimal places (e.g. 14.85 for 14.85%),
      or None if calculation cannot converge or cash flows lack positive/negative balance.
    """
    if not cashflows or len(cashflows) < 2:
        return None

    # Must contain at least one positive and one negative cash flow
    has_pos = any(c > 0 for _, c in cashflows)
    has_neg = any(c < 0 for _, c in cashflows)
    if not (has_pos and has_neg):
        return None

    # Earliest date is t0
    d0 = min(d for d, _ in cashflows)
    days = [(d - d0).days for d, _ in cashflows]
    if max(days) == 0:
        return None

    amounts = [float(c) for _, c in cashflows]

    def npv(rate: float) -> float:
        if rate <= -0.9999:
            return float("inf")
        total = 0.0
        for frac, amt in zip(days, amounts):
            total += amt / ((1.0 + rate) ** (frac / 365.0))
        return total

    def d_npv(rate: float) -> float:
        if rate <= -0.9999:
            return float("inf")
        total = 0.0
        for frac, amt in zip(days, amounts):
            t = frac / 365.0
            total -= t * amt / ((1.0 + rate) ** (t + 1.0))
        return total

    # 1. Newton-Raphson Method
    rate = guess
    for _ in range(max_iter):
        f = npv(rate)
        if abs(f) < tol:
            return round(rate * 100.0, 2)
        df = d_npv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if new_rate <= -0.99:
            new_rate = (rate - 0.99) / 2.0
        if abs(new_rate - rate) < tol:
            return round(new_rate * 100.0, 2)
        rate = new_rate

    # 2. Bisection Fallback if Newton-Raphson diverges
    low, high = -0.99, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        # Try wider search or return None
        return None

    mid = (low + high) / 2.0
    for _ in range(100):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < tol or (high - low) / 2.0 < tol:
            return round(mid * 100.0, 2)
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid

    return round(mid * 100.0, 2)
