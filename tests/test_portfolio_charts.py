import pytest
import pandas as pd
from unittest.mock import MagicMock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, date

from app.models.portfolio import Holding, Exchange
from app.services.portfolio_service import take_portfolio_snapshot, _history_cache


@pytest.mark.asyncio
async def test_holding_history_normal(auth_client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Test normal history fetch returning OHLCV, EMA20, EMA50, RSI14, avg cost, and levels."""
    _history_cache.clear()

    # Add holding
    holding = Holding(
        symbol="TATAMOTORS",
        company_name="Tata Motors Ltd",
        exchange=Exchange.NSE,
        quantity=50.0,
        avg_buy_price=600.0
    )
    db_session.add(holding)
    await db_session.commit()

    # Mock yfinance to return 30 days of data
    dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
    df = pd.DataFrame({
        "Open": [600.0 + i for i in range(30)],
        "High": [610.0 + i for i in range(30)],
        "Low": [595.0 + i for i in range(30)],
        "Close": [605.0 + i for i in range(30)],
        "Volume": [100000 + i * 100 for i in range(30)],
    }, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    monkeypatch.setattr("yfinance.Ticker", lambda sym: mock_ticker)

    resp = await auth_client.get("/api/v1/portfolio/holdings/TATAMOTORS/history?range=1m")
    assert resp.status_code == 200
    data = resp.json()

    assert data["symbol"] == "TATAMOTORS"
    assert data["range"] == "1m"
    assert data["insufficient_history"] is False
    assert len(data["candles"]) >= 10
    assert len(data["ema20"]) > 0
    assert len(data["ema50"]) > 0
    assert len(data["rsi14"]) > 0
    assert data["avg_cost"] == 600.0
    assert data["stop_loss"] is not None
    assert data["target_1"] is not None
    assert data["target_2"] is not None


@pytest.mark.asyncio
async def test_holding_history_insufficient_data(auth_client: AsyncClient, monkeypatch):
    """Test insufficient history (<10 candles) returns insufficient_history=True."""
    _history_cache.clear()

    # Mock yfinance to return only 5 days
    dates = pd.date_range(end=datetime.now(), periods=5, freq="D")
    df = pd.DataFrame({
        "Open": [100.0, 102.0, 101.0, 103.0, 105.0],
        "High": [105.0, 106.0, 104.0, 107.0, 108.0],
        "Low": [98.0, 99.0, 100.0, 101.0, 102.0],
        "Close": [103.0, 104.0, 102.0, 105.0, 106.0],
        "Volume": [5000, 6000, 5500, 7000, 8000],
    }, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    monkeypatch.setattr("yfinance.Ticker", lambda sym: mock_ticker)

    resp = await auth_client.get("/api/v1/portfolio/holdings/NEWSYM/history?range=1m")
    assert resp.status_code == 200
    data = resp.json()

    assert data["insufficient_history"] is True
    assert len(data["candles"]) == 5
    assert "Fewer than 10 candles" in (data["message"] or "")


@pytest.mark.asyncio
async def test_holding_history_yfinance_failure(auth_client: AsyncClient, monkeypatch):
    """Test yfinance network failure returns clear 502 error."""
    _history_cache.clear()

    def mock_fail_ticker(sym):
        raise ConnectionError("Remote yfinance server timeout")

    monkeypatch.setattr("yfinance.Ticker", mock_fail_ticker)

    resp = await auth_client.get("/api/v1/portfolio/holdings/ERRORSYM/history?range=3m")
    assert resp.status_code == 502
    err_body = resp.json()
    assert "Failed to fetch market history from yfinance" in err_body["detail"]


@pytest.mark.asyncio
async def test_portfolio_snapshots_match_summary(auth_client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Test portfolio snapshots totals match /portfolio/summary."""
    # Seed 2 holdings
    h1 = Holding(
        symbol="INFY",
        company_name="Infosys Limited",
        exchange=Exchange.NSE,
        quantity=10.0,
        avg_buy_price=1400.0
    )
    h2 = Holding(
        symbol="TCS",
        company_name="Tata Consultancy Services",
        exchange=Exchange.NSE,
        quantity=5.0,
        avg_buy_price=3500.0
    )
    db_session.add_all([h1, h2])
    await db_session.commit()

    # Mock live prices
    async def mock_bulk_prices(pairs):
        return {
            "INFY.NS": (1500.0, 2.0),
            "TCS.NS": (3600.0, 1.5),
        }
    monkeypatch.setattr("app.services.portfolio_service.get_live_prices_bulk", mock_bulk_prices)

    # 1. Fetch /portfolio/summary
    sum_resp = await auth_client.get("/api/v1/portfolio/summary")
    assert sum_resp.status_code == 200
    summary = sum_resp.json()

    # 2. Take a snapshot
    snap = await take_portfolio_snapshot(db_session, snapshot_date=date(2026, 10, 6))
    assert snap is not None

    # 3. Fetch /portfolio/snapshots
    snap_resp = await auth_client.get("/api/v1/portfolio/snapshots")
    assert snap_resp.status_code == 200
    snapshots = snap_resp.json()

    assert len(snapshots) >= 1
    today_snap = next(s for s in snapshots if s["date"] == "2026-10-06")

    # Verify snapshot totals match summary exactly
    assert today_snap["invested"] == summary["total_invested"]
    assert today_snap["current_value"] == summary["current_value"]
    assert today_snap["pnl"] == summary["total_unrealized_pnl"]
    priced_count = summary["holdings_count"] - summary["unpriced_count"]
    assert today_snap["priced_count"] == priced_count
