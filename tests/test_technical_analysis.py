import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.portfolio import TechnicalDiagnosis
from app.services.technical_analysis_service import (
    compute_wilder_rsi,
    compute_atr,
    compute_trailing_stop_series,
    find_swing_highs,
    compute_targets_and_stops,
    compute_technical_diagnosis,
    log_technical_diagnosis,
    evaluate_open_diagnoses,
    get_technical_diagnosis_scorecard,
    DISCLAIMER_TEXT,
)


def test_wilder_rsi_against_1978_reference_series():
    """
    Test Wilder's exact 14-period RSI smoothing against J. Welles Wilder Jr.'s
    original 1978 reference dataset from 'New Concepts in Technical Trading Systems' (Table 4).
    """
    prices = pd.Series([
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64
    ])

    rsi_series = compute_wilder_rsi(prices, period=14)

    # First 14 bars are warmup (indices 0 to 13 are NaN)
    for i in range(14):
        assert pd.isna(rsi_series.iloc[i]), f"Index {i} should be NaN during warmup"

    # Bar 15 (index 14, 14th change): Wilder's textbook gives 70.46 / 70.53
    assert abs(rsi_series.iloc[14] - 70.46) < 0.1, f"Expected ~70.46, got {rsi_series.iloc[14]}"

    # Bar 16 (index 15): Wilder gives 66.25
    assert abs(rsi_series.iloc[15] - 66.25) < 0.1, f"Expected ~66.25, got {rsi_series.iloc[15]}"

    # Bar 17 (index 16): Wilder gives 66.48
    assert abs(rsi_series.iloc[16] - 66.48) < 0.1, f"Expected ~66.48, got {rsi_series.iloc[16]}"

    # Bar 18 (index 17): Wilder gives 69.35
    assert abs(rsi_series.iloc[17] - 69.35) < 0.1, f"Expected ~69.35, got {rsi_series.iloc[17]}"

    # Bar 19 (index 18): Wilder gives 66.29
    assert abs(rsi_series.iloc[18] - 66.29) < 0.1, f"Expected ~66.29, got {rsi_series.iloc[18]}"

    # Bar 20 (index 19): Wilder gives 57.92
    assert abs(rsi_series.iloc[19] - 57.92) < 0.1, f"Expected ~57.92, got {rsi_series.iloc[19]}"


def test_rsi_neutral_status_range_40_to_60():
    """
    Requirement 4: Neutral wording at RSI 40-60 ('Neutral / Range-bound', not 'Healthy Trend').
    """
    dates = pd.date_range("2026-01-01", periods=25, freq="D")
    # Alternating prices to produce balanced RSI between 40 and 60
    prices = [100.0 + (1.0 if i % 2 == 0 else -0.5) for i in range(25)]
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + 1.0 for p in prices],
        "Low": [p - 1.0 for p in prices],
        "Close": prices,
    }, index=dates)

    diag = compute_technical_diagnosis(df, avg_buy_price=100.0)
    assert diag["rsi"] is not None
    assert 40.0 <= diag["rsi"] <= 60.0
    assert diag["rsi_status"] == "Neutral / Range-bound"
    assert "Healthy Trend" not in diag["rsi_status"]


def test_atr_and_ratcheting_trailing_stop():
    """
    Requirement 2: Trailing stop only moves up (highest close minus 2 x ATR).
    """
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    # Upward rally followed by a drop
    closes = [100.0 + i * 2.0 for i in range(20)] + [140.0 - i * 3.0 for i in range(10)]
    df = pd.DataFrame({
        "Open": closes,
        "High": [c + 2.0 for c in closes],
        "Low": [c - 2.0 for c in closes],
        "Close": closes,
    }, index=dates)

    atr = compute_atr(df, period=14)
    assert not pd.isna(atr.iloc[-1])
    assert atr.iloc[-1] > 0

    ts_series = compute_trailing_stop_series(df, atr).dropna()
    # Trailing stop must be monotonically non-decreasing
    for i in range(1, len(ts_series)):
        assert ts_series.iloc[i] >= ts_series.iloc[i - 1], (
            f"Trailing stop decreased at index {i}: {ts_series.iloc[i]} < {ts_series.iloc[i - 1]}"
        )


def test_targets_swing_highs_and_not_flat_8_pct():
    """
    Requirement 3:
    Target 1 = nearest real resistance (recent swing high).
    Target 2 = next swing high or a 2:1 reward-to-risk level, NOT a flat +8%.
    Show 'estimated' next to them.
    """
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    # Base prices with distinct swing peaks at index 10 (peak 125) and index 20 (peak 135)
    prices = [100.0] * 30
    highs = [102.0] * 30
    lows = [98.0] * 30

    # Swing high 1 at bar 10: 125.0
    highs[10] = 125.0
    prices[10] = 120.0
    # Swing high 2 at bar 20: 138.0
    highs[20] = 138.0
    prices[20] = 132.0

    # Current price at bar 29: 110.0
    prices[-1] = 110.0
    highs[-1] = 112.0
    lows[-1] = 108.0

    df = pd.DataFrame({
        "Open": prices,
        "High": highs,
        "Low": lows,
        "Close": prices,
    }, index=dates)

    diag = compute_technical_diagnosis(df, avg_buy_price=105.0)

    # Target 1 should be the first swing high above 110: 125.0
    assert diag["target_1"] == 125.0
    # Target 2 should be the next swing high above Target 1: 138.0
    assert diag["target_2"] == 138.0

    # Verify NOT flat 1.08 * Target 1
    assert diag["target_2"] != round(125.0 * 1.08, 2)

    # Check estimated labels and disclaimer
    assert diag["target_1_label"] == "estimated"
    assert diag["target_2_label"] == "estimated"
    assert diag["disclaimer"] == DISCLAIMER_TEXT


def test_target_2_falls_back_to_2_to_1_reward_to_risk():
    """
    When only one swing high exists above CMP, Target 2 should be a 2:1 reward-to-risk level.
    """
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    prices = [100.0] * 20
    highs = [102.0] * 20
    lows = [98.0] * 20

    # Only one swing high above CMP (at bar 10: 120.0)
    highs[10] = 120.0
    prices[10] = 115.0

    prices[-1] = 105.0
    highs[-1] = 106.0
    lows[-1] = 104.0

    df = pd.DataFrame({"Open": prices, "High": highs, "Low": lows, "Close": prices}, index=dates)

    diag = compute_technical_diagnosis(df, avg_buy_price=105.0)
    assert diag["target_1"] == 120.0
    # Target 2 must strictly be greater than Target 1 and NOT a flat +8%
    assert diag["target_2"] > diag["target_1"]
    assert diag["target_2"] != round(diag["target_1"] * 1.08, 2)


def test_disclaimer_sentence_integrity():
    """
    Requirement 6: Add the line: 'Mechanical technical levels, not a forecast or investment advice.'
    """
    assert DISCLAIMER_TEXT == "Mechanical technical levels, not a forecast or investment advice."


@pytest.mark.asyncio
async def test_log_and_evaluate_technical_diagnoses(db_session: AsyncSession):
    """
    Requirement 5: Log each diagnosis in a table, and add a daily job that records
    whether price later hit target or stop first.
    """
    # 1. Log diagnosis for day T - 2
    past_date = date.today() - timedelta(days=2)
    diag = await log_technical_diagnosis(
        session=db_session,
        symbol="TESTHIT",
        price=100.0,
        stop_loss=90.0,
        trailing_stop=92.0,
        target_1=115.0,
        target_2=125.0,
        diag_date=past_date,
    )
    await db_session.commit()

    assert diag.id is not None
    assert diag.status == "OPEN"

    # Query back
    stmt = select(TechnicalDiagnosis).where(TechnicalDiagnosis.symbol == "TESTHIT")
    res = await db_session.execute(stmt)
    saved = res.scalars().first()
    assert saved is not None
    assert saved.price == 100.0
    assert saved.stop_loss == 90.0


@pytest.mark.asyncio
async def test_technical_diagnosis_scorecard_threshold_30(db_session: AsyncSession):
    """
    Requirement 5: Show the hit rate in a small scorecard once there are at least 30 closed diagnoses.
    Shows not_enough_data when < 30.
    """
    # Clear test diagnoses
    from sqlalchemy import delete
    await db_session.execute(delete(TechnicalDiagnosis))
    await db_session.commit()

    # Case A: 5 closed diagnoses (< 30)
    for i in range(5):
        d = TechnicalDiagnosis(
            date=date.today() - timedelta(days=i + 5),
            symbol=f"STK{i}",
            price=100.0,
            stop_loss=90.0,
            trailing_stop=92.0,
            target_1=110.0,
            target_2=120.0,
            status="TARGET_HIT" if i % 2 == 0 else "STOP_HIT",
            closed_at_date=date.today() - timedelta(days=i + 1),
            hit_price=110.0 if i % 2 == 0 else 90.0,
            hit_type="TARGET_1" if i % 2 == 0 else "STOP_LOSS",
        )
        db_session.add(d)
    await db_session.commit()

    scorecard_under = await get_technical_diagnosis_scorecard(db_session)
    assert scorecard_under["status"] == "not_enough_data"
    assert scorecard_under["closed_diagnoses"] == 5
    assert scorecard_under["min_required"] == 30
    assert scorecard_under["hit_rate_pct"] is None
    assert "Collecting data (5/30 closed diagnoses)" in scorecard_under["message"]
    assert DISCLAIMER_TEXT in scorecard_under["disclaimer"]

    # Case B: Add 25 more closed diagnoses (total 30 closed)
    # 15 more target hits (indices 5..19) + 3 from before = 18 target hits (60%)
    for i in range(5, 30):
        is_target = i < 20
        d = TechnicalDiagnosis(
            date=date.today() - timedelta(days=i + 5),
            symbol=f"STK{i}",
            price=100.0,
            stop_loss=90.0,
            trailing_stop=92.0,
            target_1=110.0,
            target_2=120.0,
            status="TARGET_HIT" if is_target else "STOP_HIT",
            closed_at_date=date.today() - timedelta(days=i + 1),
            hit_price=110.0 if is_target else 90.0,
            hit_type="TARGET_1" if is_target else "STOP_LOSS",
        )
        db_session.add(d)
    await db_session.commit()

    scorecard_active = await get_technical_diagnosis_scorecard(db_session)
    assert scorecard_active["status"] == "active"
    assert scorecard_active["closed_diagnoses"] == 30
    assert scorecard_active["target_hits"] == 18
    assert scorecard_active["stop_hits"] == 12
    assert scorecard_active["hit_rate_pct"] == 60.0
    assert "Hit rate: 60.0% across 30 closed" in scorecard_active["message"]
