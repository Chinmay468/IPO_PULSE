import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import SuggestionLog
from app.services.market_shares_service import (
    calculate_atr,
    compute_atr_levels,
    evaluate_stock_prefilters,
    evaluate_position_sizing,
    log_suggestion,
    evaluate_open_suggestions,
    get_suggestion_scorecard,
    format_scorecard_message,
    format_shares_summary_card,
    TECHNICAL_SWING_CANDIDATES
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ATR & LEVEL TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_calculate_atr_valid_candles():
    # 20 candles with clear High, Low, Close
    highs = [100 + i + 2 for i in range(20)]
    lows = [100 + i - 2 for i in range(20)]
    closes = [100 + i for i in range(20)]
    df = pd.DataFrame({'High': highs, 'Low': lows, 'Close': closes})

    atr = calculate_atr(df, period=14)
    assert atr is not None
    assert atr > 0
    # True range is 4 per day (high - low = 4)
    assert abs(atr - 4.0) < 0.1


def test_calculate_atr_insufficient_data():
    df = pd.DataFrame({'High': [100], 'Low': [98], 'Close': [99]})
    assert calculate_atr(df, period=14) is None
    assert calculate_atr(None) is None


def test_compute_atr_levels_guarantees_1_to_2_rr():
    entry = 1000.0
    atr = 50.0

    levels = compute_atr_levels(entry, atr)
    assert levels["stop_loss"] == 1000.0 - (1.5 * 50.0)  # 925.0
    assert levels["target_price"] == 1000.0 + (3.0 * 50.0)  # 1150.0

    # Risk = 75, Reward = 150 -> Exactly 1:2 R:R
    risk = entry - levels["stop_loss"]
    reward = levels["target_price"] - entry
    assert round(reward / risk, 1) == 2.0
    assert levels["upside_pct"] == 15.0
    assert levels["downside_pct"] == 7.5


# ─────────────────────────────────────────────────────────────────────────────
# 2. PRE-FILTER TESTS (NEVER DEFAULT ON MISSING DATA)
# ─────────────────────────────────────────────────────────────────────────────

def test_prefilter_skips_when_data_missing():
    # Empty DF
    passed, reason, _ = evaluate_stock_prefilters(pd.DataFrame(), pd.DataFrame())
    assert not passed
    assert "Missing" in reason

    # Insufficient bars (<63d stock or <200d Nifty)
    stock_df = pd.DataFrame({
        'Open': [100]*50, 'High': [102]*50, 'Low': [98]*50, 'Close': [100]*50, 'Volume': [500000]*50
    })
    nifty_df = pd.DataFrame({
        'Open': [20000]*210, 'High': [20100]*210, 'Low': [19900]*210, 'Close': [20000]*210, 'Volume': [1e7]*210
    })
    passed, reason, _ = evaluate_stock_prefilters(stock_df, nifty_df)
    assert not passed
    assert "Insufficient" in reason


def test_prefilter_skips_circuit_limit():
    # High == Low on latest bar
    stock_df = pd.DataFrame({
        'Open': [100]*70, 'High': [102]*69 + [105], 'Low': [98]*69 + [105], 'Close': [100]*69 + [105], 'Volume': [500000]*70
    })
    nifty_df = pd.DataFrame({
        'Open': [20000]*210, 'High': [20100]*210, 'Low': [19900]*210, 'Close': [20000]*210, 'Volume': [1e7]*210
    })
    passed, reason, _ = evaluate_stock_prefilters(stock_df, nifty_df)
    assert not passed
    assert "circuit" in reason.lower()


def test_prefilter_skips_low_volume():
    # ADV20 < 100,000
    stock_df = pd.DataFrame({
        'Open': [100]*70, 'High': [102]*70, 'Low': [98]*70, 'Close': [100]*70, 'Volume': [50000]*70
    })
    nifty_df = pd.DataFrame({
        'Open': [20000]*210, 'High': [20100]*210, 'Low': [19900]*210, 'Close': [20000]*210, 'Volume': [1e7]*210
    })
    passed, reason, _ = evaluate_stock_prefilters(stock_df, nifty_df)
    assert not passed
    assert "liquidity" in reason.lower() or "adv20" in reason.lower()


def test_prefilter_skips_price_below_ema50():
    # Declining price below EMA50
    prices = [200 - i for i in range(70)]
    stock_df = pd.DataFrame({
        'Open': prices, 'High': [p+1 for p in prices], 'Low': [p-1 for p in prices], 'Close': prices, 'Volume': [200000]*70
    })
    nifty_df = pd.DataFrame({
        'Open': [20000]*210, 'High': [20100]*210, 'Low': [19900]*210, 'Close': [20000]*210, 'Volume': [1e7]*210
    })
    passed, reason, _ = evaluate_stock_prefilters(stock_df, nifty_df)
    assert not passed
    assert "below ema50" in reason.lower()


def test_prefilter_skips_when_nifty_below_ema200_and_low_score():
    # Nifty strongly declining below EMA200
    nifty_prices = [25000 - (i * 20) for i in range(210)]  # ends around 20800
    nifty_df = pd.DataFrame({
        'Open': nifty_prices, 'High': [p+50 for p in nifty_prices], 'Low': [p-50 for p in nifty_prices],
        'Close': nifty_prices, 'Volume': [1e7]*210
    })

    stock_prices = [100 + i for i in range(70)]
    stock_df = pd.DataFrame({
        'Open': stock_prices, 'High': [p+2 for p in stock_prices], 'Low': [p-2 for p in stock_prices],
        'Close': stock_prices, 'Volume': [500000]*70
    })

    # With normal score (70) -> should be skipped due to Nifty < EMA200
    passed, reason, _ = evaluate_stock_prefilters(stock_df, nifty_df, score=70.0)
    assert not passed
    assert "regime risk" in reason.lower()

    # With very high score (85) -> should pass!
    passed2, reason2, _ = evaluate_stock_prefilters(stock_df, nifty_df, score=85.0)
    assert passed2
    assert "Passed" in reason2


# ─────────────────────────────────────────────────────────────────────────────
# 3. POSITION SIZING TESTS (25% CAP & WARNINGS)
# ─────────────────────────────────────────────────────────────────────────────

def test_position_sizing_warns_over_25_pct():
    portfolio = {
        "total_current_value": 100000.0,
        "holdings": [
            {"symbol": "HDFCBANK", "quantity": 40, "current_value": 28000.0}  # 28% of portfolio!
        ]
    }
    res = evaluate_position_sizing("HDFCBANK", entry_price=700.0, portfolio_summary=portfolio)
    assert not res["can_add"]
    assert res["suggested_max_qty"] == 0
    assert "⚠️ Position limit reached" in res["warning"]


def test_position_sizing_allows_under_25_pct():
    portfolio = {
        "total_current_value": 100000.0,
        "holdings": [
            {"symbol": "NTPC", "quantity": 30, "current_value": 9000.0}  # 9% of portfolio
        ]
    }
    # 25% of 100k is 25,000. Existing is 9,000. Remaining room is 16,000.
    # Entry price 300 -> 16,000 / 300 = 53 shares
    res = evaluate_position_sizing("NTPC", entry_price=300.0, portfolio_summary=portfolio)
    assert res["can_add"]
    assert res["suggested_max_qty"] == 53
    assert res["warning"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. SUGGESTION LOG & 45-DAY EXPIRY TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_suggestion_deduplicates(db_session: AsyncSession):
    item = {
        "symbol": "HDFCBANK",
        "current_price": 720.0,
        "target_price": 770.0,
        "stop_loss": 695.0,
        "atr": 16.5,
        "thesis": "Strong base"
    }

    log1 = await log_suggestion(db_session, item)
    assert log1.id is not None
    assert log1.status == "open"
    assert log1.date == date.today()

    # Second call on same day returns existing record
    log2 = await log_suggestion(db_session, item)
    assert log1.id == log2.id


@pytest.mark.asyncio
async def test_evaluate_open_suggestions_45_day_expiry(db_session: AsyncSession):
    # Create an old open suggestion from 50 days ago
    old_date = date.today() - timedelta(days=50)
    old_sugg = SuggestionLog(
        date=old_date,
        symbol="NTPC",
        entry_price=300.0,
        target=330.0,
        stop=285.0,
        atr=10.0,
        status="open"
    )
    db_session.add(old_sugg)
    await db_session.commit()

    with patch("app.services.market_shares_service.get_live_price", new_callable=AsyncMock) as mock_price:
        mock_price.return_value = (310.0, 1.2)
        summary = await evaluate_open_suggestions(db_session)

        assert summary["expired"] >= 1
        await db_session.refresh(old_sugg)
        assert old_sugg.status == "expired"
        assert old_sugg.exit_date == date.today()
        assert old_sugg.exit_price == 310.0
        assert old_sugg.return_pct == round(((310.0 - 300.0) / 300.0) * 100, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 5. SCORECARD TESTS (<30 PICKS VS 30+ PICKS)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scorecard_not_enough_data(db_session: AsyncSession):
    # Empty or few records
    scorecard = await get_suggestion_scorecard(db_session)
    assert scorecard["status"] == "not_enough_data"
    assert scorecard["min_required"] == 30
    assert "Not enough data" in scorecard["message"]

    msg = format_scorecard_message(scorecard)
    assert "Not enough data yet" in msg
    assert "30" in msg


@pytest.mark.asyncio
async def test_scorecard_active_at_30_closed_picks(db_session: AsyncSession):
    today = date.today()
    # Add 30 closed suggestions
    for i in range(20):
        # 20 winners
        db_session.add(SuggestionLog(
            date=today - timedelta(days=20),
            symbol=f"WINNER_{i}",
            entry_price=100.0,
            target=115.0,
            stop=92.5,
            atr=5.0,
            status="target",
            exit_date=today - timedelta(days=10),
            exit_price=115.0,
            return_pct=15.0
        ))
    for i in range(10):
        # 10 stopped
        db_session.add(SuggestionLog(
            date=today - timedelta(days=20),
            symbol=f"STOPPED_{i}",
            entry_price=100.0,
            target=115.0,
            stop=92.5,
            atr=5.0,
            status="stop",
            exit_date=today - timedelta(days=12),
            exit_price=92.5,
            return_pct=-7.5
        ))
    await db_session.commit()

    with patch("app.services.market_shares_service.get_nifty_period_return", new_callable=AsyncMock) as mock_nifty:
        mock_nifty.return_value = 3.5

        scorecard = await get_suggestion_scorecard(db_session)
        assert scorecard["status"] == "active"
        assert scorecard["closed_picks"] >= 30
        assert scorecard["target_hits"] >= 20
        assert scorecard["stop_hits"] >= 10
        assert scorecard["hit_rate_pct"] >= 60.0

        msg = format_scorecard_message(scorecard)
        assert "Hit Rate" in msg
        assert "Performance vs Nifty" in msg
        assert "Disclaimer" in msg


@pytest.mark.asyncio
async def test_get_portfolio_scorecard_api_endpoint(client, db_session, auth_headers):
    resp = await client.get("/api/v1/portfolio/scorecard", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("not_enough_data", "active")


# ─────────────────────────────────────────────────────────────────────────────
# 6. DISCLAIMER INTEGRITY TEST
# ─────────────────────────────────────────────────────────────────────────────

def test_summary_card_contains_disclaimer_and_atr_risk_rules():
    sample_shares = [
        {
            "symbol": "HDFCBANK",
            "company_name": "HDFC Bank",
            "sector": "Banking",
            "current_price": 720.0,
            "entry_range": "₹710 - ₹725",
            "target_price": 770.0,
            "stop_loss": 695.0,
            "atr": 16.5,
            "upside_pct": 6.9,
            "downside_pct": 3.5,
            "thesis": "Historical P/B support",
            "position_warning": None,
            "suggested_max_qty": 35
        }
    ]
    card = format_shares_summary_card(sample_shares)
    assert "Not investment advice, GMP/technical levels are estimates" in card
    assert "Mechanical levels (ATR-based" in card
    assert "strict ATR stop-loss (-1.5×ATR)" in card
    assert "Minimum 1:2 Risk/Reward ratio" in card
    assert "Maximum 25% single-stock allocation cap" in card
    assert "Hard trade expiry after 45 days" in card
