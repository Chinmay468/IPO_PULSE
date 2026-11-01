import io
import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import Holding, Transaction, TransactionType, Exchange
from app.models.price_history import PriceHistory, DataIssue
from app.services.nse_holidays import (
    is_trading_day,
    get_trading_days,
    get_missing_trading_days,
    NSE_HOLIDAYS
)
from app.services.price_validation import validate_candle
from app.services.price_history_service import (
    execute_upsert_candles,
    validate_and_upsert_raw_candles,
    get_price_history_with_fallback,
    compute_portfolio_history_over_time,
    export_price_history_stream,
    get_clean_adjusted_ohlcv,
    clean_symbol
)
from app.auth import create_access_token


@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": "testuser", "role": "admin", "user_id": 1})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_upsert_idempotency(db_session: AsyncSession):
    """
    Test that upserting the exact same candles multiple times:
    - Never creates duplicate rows (row count stays constant).
    - Idempotently updates fields (e.g. close, volume) if changed.
    """
    symbol = "RELIANCE"
    exchange = "NSE"
    test_dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]

    rows_batch_1 = [
        {
            "symbol": symbol,
            "exchange": exchange,
            "date": d,
            "open": 2500.0,
            "high": 2550.0,
            "low": 2490.0,
            "close": 2520.0,
            "adj_close": 2520.0,
            "volume": 100000,
            "source": "yfinance"
        }
        for d in test_dates
    ]

    # First upsert
    count1 = await execute_upsert_candles(db_session, rows_batch_1)
    assert count1 == 3

    res1 = await db_session.execute(
        select(func.count(PriceHistory.id)).where(PriceHistory.symbol == symbol)
    )
    assert res1.scalar() == 3

    # Second upsert with updated close and volume for date 2026-01-07
    rows_batch_2 = [
        {
            "symbol": symbol,
            "exchange": exchange,
            "date": date(2026, 1, 7),
            "open": 2500.0,
            "high": 2570.0,
            "low": 2490.0,
            "close": 2565.0,  # updated
            "adj_close": 2565.0,
            "volume": 150000,  # updated
            "source": "yfinance"
        }
    ]
    count2 = await execute_upsert_candles(db_session, rows_batch_2)
    assert count2 == 1

    # Total row count must still be 3
    res2 = await db_session.execute(
        select(func.count(PriceHistory.id)).where(PriceHistory.symbol == symbol)
    )
    assert res2.scalar() == 3

    # Verify updated values
    row = (await db_session.execute(
        select(PriceHistory).where(PriceHistory.symbol == symbol, PriceHistory.date == date(2026, 1, 7))
    )).scalar_one()
    assert row.close == 2565.0
    assert row.volume == 150000


@pytest.mark.asyncio
async def test_validation_rules_rejection(db_session: AsyncSession):
    """
    Test validation rejection rules:
    - high < low
    - close outside [low, high]
    - any price null or <= 0
    Corrupt candles must be rejected and logged to data_issues table.
    """
    symbol = "TCS"
    exchange = "NSE"

    corrupt_data = pd.DataFrame([
        # 1. High < Low
        {"Open": 3500.0, "High": 3400.0, "Low": 3600.0, "Close": 3550.0, "Volume": 1000},
        # 2. Close outside [Low, High] (Close > High)
        {"Open": 3500.0, "High": 3600.0, "Low": 3450.0, "Close": 3700.0, "Volume": 1000},
        # 3. Close outside [Low, High] (Close < Low)
        {"Open": 3500.0, "High": 3600.0, "Low": 3450.0, "Close": 3300.0, "Volume": 1000},
        # 4. Zero / negative price
        {"Open": 0.0, "High": 3600.0, "Low": 3450.0, "Close": 3500.0, "Volume": 1000},
        # 5. Valid candle
        {"Open": 3500.0, "High": 3600.0, "Low": 3450.0, "Close": 3550.0, "Volume": 1000},
    ], index=pd.date_range("2026-01-05", periods=5, freq="D"))

    result = await validate_and_upsert_raw_candles(db_session, symbol, exchange, corrupt_data)
    assert result["upserted"] == 1
    assert result["rejected"] == 4

    # Verify only the valid candle was stored in price_history
    ph_rows = (await db_session.execute(
        select(PriceHistory).where(PriceHistory.symbol == symbol)
    )).scalars().all()
    assert len(ph_rows) == 1
    assert ph_rows[0].close == 3550.0

    # Verify data_issues table recorded the 4 errors
    issues = (await db_session.execute(
        select(DataIssue).where(DataIssue.symbol == symbol)
    )).scalars().all()
    issue_types = [iss.issue_type for iss in issues]
    assert "HIGH_LESS_THAN_LOW" in issue_types
    assert "CLOSE_OUT_OF_BOUNDS" in issue_types
    assert "NULL_OR_ZERO_PRICE" in issue_types


@pytest.mark.asyncio
async def test_validation_40_pct_jump_flag(db_session: AsyncSession):
    """
    Test that a single-day change exceeding 40% is kept (inserted) but
    flagged in data_issues for review (possible unadjusted split/bonus).
    """
    symbol = "INFY"
    exchange = "NSE"

    jump_data = pd.DataFrame([
        # Day 1: Close = 1500
        {"Open": 1490.0, "High": 1520.0, "Low": 1480.0, "Close": 1500.0, "Volume": 10000},
        # Day 2: Close = 2250 (+50% jump)
        {"Open": 2100.0, "High": 2300.0, "Low": 2050.0, "Close": 2250.0, "Volume": 15000},
    ], index=pd.to_datetime(["2026-01-05", "2026-01-06"]))

    result = await validate_and_upsert_raw_candles(db_session, symbol, exchange, jump_data)
    assert result["upserted"] == 2
    assert result["rejected"] == 0

    # Verify flag in data_issues
    issues = (await db_session.execute(
        select(DataIssue).where(DataIssue.symbol == symbol, DataIssue.issue_type == "LARGE_PRICE_JUMP")
    )).scalars().all()
    assert len(issues) >= 1
    assert issues[0].severity == "REVIEW"
    assert "50.0%" in issues[0].details


@pytest.mark.asyncio
async def test_validation_trading_gap_flag(db_session: AsyncSession):
    """
    Test that a gap of more than one trading day is flagged as TRADING_GAP in data_issues.
    """
    symbol = "HDFCBANK"
    exchange = "NSE"

    # Monday 2026-01-05 and Friday 2026-01-09 (skips Tue, Wed, Thu -> 3 trading days missing)
    gap_data = pd.DataFrame([
        {"Open": 1600.0, "High": 1620.0, "Low": 1590.0, "Close": 1610.0, "Volume": 20000},
        {"Open": 1610.0, "High": 1630.0, "Low": 1600.0, "Close": 1620.0, "Volume": 25000},
    ], index=pd.to_datetime(["2026-01-05", "2026-01-09"]))

    result = await validate_and_upsert_raw_candles(db_session, symbol, exchange, gap_data)
    assert result["upserted"] == 2

    issues = (await db_session.execute(
        select(DataIssue).where(DataIssue.symbol == symbol, DataIssue.issue_type == "TRADING_GAP")
    )).scalars().all()
    assert len(issues) >= 1
    assert "3 missing trading days" in issues[0].details


def test_holiday_handling():
    """
    Test NSE holiday calendar and trading day evaluation:
    - Weekends (Sat/Sun) are non-trading days
    - Known NSE holidays are non-trading days
    - Regular weekdays are trading days
    - get_trading_days and get_missing_trading_days
    """
    # 1. Weekend checks
    sat = date(2026, 1, 10)
    sun = date(2026, 1, 11)
    mon = date(2026, 1, 12)
    assert not is_trading_day(sat)
    assert not is_trading_day(sun)
    assert is_trading_day(mon)

    # 2. Known holiday checks (Republic Day 2026-01-26, Christmas 2025-12-25)
    republic_day = date(2026, 1, 26)  # Monday
    assert republic_day in NSE_HOLIDAYS
    assert not is_trading_day(republic_day)

    christmas = date(2025, 12, 25)
    assert christmas in NSE_HOLIDAYS
    assert not is_trading_day(christmas)

    # 3. Trading days generator
    days = get_trading_days(date(2026, 1, 5), date(2026, 1, 11))  # Mon-Sun
    assert len(days) == 5  # Mon, Tue, Wed, Thu, Fri (Sat & Sun excluded)

    # 4. Missing trading days calculation
    present_set = {date(2026, 1, 5), date(2026, 1, 7)}  # Mon, Wed present
    missing = get_missing_trading_days(present_set, date(2026, 1, 5), date(2026, 1, 9))
    # Expected: Tue 2026-01-06, Thu 2026-01-08, Fri 2026-01-09
    assert missing == [date(2026, 1, 6), date(2026, 1, 8), date(2026, 1, 9)]


@pytest.mark.asyncio
async def test_portfolio_history_with_missing_price(db_session: AsyncSession):
    """
    Test building portfolio value over time:
    - Multiple holdings and transactions.
    - Excludes days where a holding has no price and marks them in unpriced_holdings.
    """
    # 1. Create two holdings
    h1 = Holding(symbol="SYM_A", company_name="Company A", exchange=Exchange.NSE, quantity=10, avg_buy_price=100.0)
    h2 = Holding(symbol="SYM_B", company_name="Company B", exchange=Exchange.NSE, quantity=5, avg_buy_price=200.0)
    db_session.add_all([h1, h2])
    await db_session.flush()

    # 2. Create BUY transactions on 2026-01-05
    d_start = date(2026, 1, 5)
    tx1 = Transaction(holding_id=h1.id, transaction_type=TransactionType.BUY, quantity=10, price=100.0, transaction_date=d_start)
    tx2 = Transaction(holding_id=h2.id, transaction_type=TransactionType.BUY, quantity=5, price=200.0, transaction_date=d_start)
    db_session.add_all([tx1, tx2])
    await db_session.flush()

    # 3. Seed prices:
    # 2026-01-05: both SYM_A (100) and SYM_B (200) have prices.
    # 2026-01-06: only SYM_A (110) has price, SYM_B has NO price.
    p1 = PriceHistory(symbol="SYM_A", exchange="NSE", date=date(2026, 1, 5), open=98, high=102, low=97, close=100, adj_close=100, volume=1000)
    p2 = PriceHistory(symbol="SYM_B", exchange="NSE", date=date(2026, 1, 5), open=198, high=205, low=195, close=200, adj_close=200, volume=1000)
    p3 = PriceHistory(symbol="SYM_A", exchange="NSE", date=date(2026, 1, 6), open=100, high=112, low=99, close=110, adj_close=110, volume=1200)
    db_session.add_all([p1, p2, p3])
    await db_session.commit()

    # 4. Compute portfolio history
    history = await compute_portfolio_history_over_time(db_session)
    assert len(history) >= 2

    # Point 1 (2026-01-05): Both priced -> Value = (10*100) + (5*200) = 2000
    pt1 = [p for p in history if p["date"] == "2026-01-05"][0]
    assert pt1["current_value"] == 2000.0
    assert pt1["priced_count"] == 2
    assert pt1["has_unpriced"] is False
    assert len(pt1["unpriced_holdings"]) == 0

    # Point 2 (2026-01-06): SYM_B has NO price -> Excluded! Value = (10*110) = 1100
    pt2 = [p for p in history if p["date"] == "2026-01-06"][0]
    assert pt2["current_value"] == 1100.0
    assert pt2["priced_count"] == 1
    assert pt2["has_unpriced"] is True
    assert "SYM_B" in pt2["unpriced_holdings"]


@pytest.mark.asyncio
async def test_export_formats_and_auth(client: AsyncClient, db_session: AsyncSession, auth_headers):
    """
    Test streaming export:
    - Auth required (401 without token)
    - Supports format=csv, format=xlsx, format=parquet
    - Streams properly with correct headers
    """
    symbol = "EXPORTTEST"
    exchange = "NSE"
    p = PriceHistory(
        symbol=symbol,
        exchange=exchange,
        date=date.today() - timedelta(days=10),
        open=500.0,
        high=520.0,
        low=495.0,
        close=515.0,
        adj_close=515.0,
        volume=50000,
        source="yfinance"
    )
    db_session.add(p)
    await db_session.commit()

    # 1. Unauthorized request
    unauth_res = await client.get(f"/api/v1/data/prices/export?symbol={symbol}&format=csv")
    assert unauth_res.status_code == 401

    # 2. CSV Export
    csv_res = await client.get(f"/api/v1/data/prices/export?symbol={symbol}&format=csv", headers=auth_headers)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    assert "attachment; filename=" in csv_res.headers.get("content-disposition", "")
    assert f"prices_{symbol}" in csv_res.headers.get("content-disposition", "")
    content_str = csv_res.content.decode("utf-8")
    assert "open,high,low,close" in content_str
    assert "515.0" in content_str

    # 3. XLSX Export
    xlsx_res = await client.get(f"/api/v1/data/prices/export?symbol={symbol}&format=xlsx", headers=auth_headers)
    assert xlsx_res.status_code == 200
    assert "openxmlformats-officedocument" in xlsx_res.headers.get("content-type", "")
    assert len(xlsx_res.content) > 100  # Valid Excel binary bytes

    # 4. Parquet Export
    parquet_res = await client.get(f"/api/v1/data/prices/export?symbol={symbol}&format=parquet", headers=auth_headers)
    assert parquet_res.status_code == 200
    assert "octet-stream" in parquet_res.headers.get("content-type", "")
    # Parse parquet back with pandas to verify valid parquet stream
    pq_df = pd.read_parquet(io.BytesIO(parquet_res.content))
    assert len(pq_df) == 1
    assert pq_df.iloc[0]["close"] == 515.0


@pytest.mark.asyncio
async def test_fallback_when_yfinance_fails(db_session: AsyncSession, monkeypatch):
    """
    Test that when yfinance fails or network is down:
    - Existing cached candles in price_history are served.
    - System responds gracefully without crashing with 500 error.
    """
    symbol = "FALLBACKTEST"
    # Seed 1 candle
    p = PriceHistory(
        symbol=symbol,
        exchange="NSE",
        date=date.today() - timedelta(days=10),
        open=100.0,
        high=105.0,
        low=98.0,
        close=102.0,
        adj_close=102.0,
        volume=1000
    )
    db_session.add(p)
    await db_session.commit()

    # Mock yfinance to simulate network outage / exception
    from app.services import price_history_service
    def mock_fail(*args, **kwargs):
        raise ConnectionError("Network unreachable")

    monkeypatch.setattr(price_history_service, "_fetch_yf_candles_sync", mock_fail)

    # Call history with fallback
    res = await get_price_history_with_fallback(db_session, symbol=symbol, range_str="3m")
    assert res["symbol"] == symbol
    # Served cached candle even though yfinance failed
    assert len(res["candles"]) >= 1
    assert res["candles"][0]["close"] == 102.0


@pytest.mark.asyncio
async def test_research_hook_clean_adjusted_ohlcv(db_session: AsyncSession):
    """
    Test the walk-forward evaluation research hook:
    Returns clean, corporate-adjusted OHLCV DataFrame with monotonic DatetimeIndex.
    """
    symbol = "RESEARCHTEST"
    exchange = "NSE"

    p1 = PriceHistory(symbol=symbol, exchange=exchange, date=date(2026, 1, 5), open=100, high=105, low=95, close=100, adj_close=50, volume=1000)
    p2 = PriceHistory(symbol=symbol, exchange=exchange, date=date(2026, 1, 6), open=102, high=108, low=98, close=104, adj_close=52, volume=1500)
    db_session.add_all([p1, p2])
    await db_session.commit()

    df = await get_clean_adjusted_ohlcv(symbol, exchange=exchange, db=db_session)
    assert not df.empty
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing
    # Verify adjustment: close was 100 with adj_close 50 (factor 0.5) -> Open adjusted to 50
    assert df.iloc[0]["Open"] == 50.0
    assert df.iloc[0]["Close"] == 50.0
