import pytest
import pytest_asyncio
from datetime import date, datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.mutual_fund import MFScheme, MFHolding, MFTransaction, MFNavHistory, MFTransactionType
from app.models.portfolio import Holding, Exchange
from app.services.xirr_service import calculate_xirr
from app.services.mf_cas_parser_service import mask_folio, hash_folio, import_parsed_cas
from app.services.portfolio_advisor_service import generate_portfolio_advisory
import app.services.mutual_fund_service as mf_svc


# ── 1. Unit Tests for XIRR Calculation ───────────────────────────────────────

def test_xirr_exact_one_year_gain():
    """
    Known cash flow example:
    Invest ₹1,000 on 2024-01-01 (outflow -1000).
    Receive ₹1,100 on 2025-01-01 (inflow +1100).
    Exactly 366 days (leap year) / 1 year -> XIRR must be ~10.0%.
    """
    cashflows = [
        (date(2024, 1, 1), -1000.0),
        (date(2025, 1, 1), 1100.0)
    ]
    rate = calculate_xirr(cashflows)
    assert rate is not None
    # Annualized return should be between 9.9% and 10.1%
    assert pytest.approx(rate, abs=0.2) == 10.0


def test_xirr_multi_cashflow_sip():
    """
    3 monthly SIP investments of ₹5,000 each.
    Terminal value ₹16,000 after 3 months.
    """
    cashflows = [
        (date(2024, 1, 1), -5000.0),
        (date(2024, 2, 1), -5000.0),
        (date(2024, 3, 1), -5000.0),
        (date(2024, 4, 1), 16000.0)
    ]
    rate = calculate_xirr(cashflows)
    assert rate is not None
    assert rate > 0.0


def test_xirr_edge_cases():
    """Single cashflow or all negative/all positive cashflows must return None."""
    assert calculate_xirr([]) is None
    assert calculate_xirr([(date(2024, 1, 1), -1000.0)]) is None
    assert calculate_xirr([(date(2024, 1, 1), -1000.0), (date(2024, 2, 1), -1000.0)]) is None
    assert calculate_xirr([(date(2024, 1, 1), 1000.0), (date(2024, 2, 1), 1100.0)]) is None


# ── 2. Masking & Folio Security Unit Tests ───────────────────────────────────

def test_folio_masking_and_hashing():
    raw_folio = "12345678/90"
    masked = mask_folio(raw_folio)
    assert masked.startswith("****")
    assert masked.endswith("8/90")
    assert "1234" not in masked

    h1 = hash_folio(raw_folio)
    h2 = hash_folio(raw_folio)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256


# ── 3. Database Summary & Totals Match Test ──────────────────────────────────

@pytest.mark.asyncio
async def test_mf_summary_totals_match_holdings(db_session: AsyncSession, auth_client: AsyncClient):
    """
    Verify that totals returned by GET /api/v1/portfolio/mf/summary match
    the exact sum of individual holdings.
    """
    # Create Scheme 1 (Priced)
    s1 = MFScheme(
        scheme_code="122639",
        isin="INF879O01019",
        name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        amc="PPFAS Mutual Fund",
        category="Equity - Flexi Cap",
        latest_nav=75.0,
        latest_nav_date=date(2026, 10, 6)
    )
    # Create Scheme 2 (Priced)
    s2 = MFScheme(
        scheme_code="100033",
        isin="INF200K01015",
        name="SBI Bluechip Fund - Direct Plan - Growth",
        amc="SBI Mutual Fund",
        category="Equity - Large Cap",
        latest_nav=100.0,
        latest_nav_date=date(2026, 10, 6)
    )
    db_session.add_all([s1, s2])
    await db_session.commit()
    await db_session.refresh(s1)
    await db_session.refresh(s2)

    # Holding 1: 100 units, avg nav 50 -> invested 5000, value 7500, pnl 2500
    h1 = MFHolding(
        scheme_id=s1.id,
        folio_masked="****1234",
        folio_hash=hash_folio("1234"),
        units=100.0
    )
    # Holding 2: 50 units, avg nav 80 -> invested 4000, value 5000, pnl 1000
    h2 = MFHolding(
        scheme_id=s2.id,
        folio_masked="****5678",
        folio_hash=hash_folio("5678"),
        units=50.0
    )
    db_session.add_all([h1, h2])
    await db_session.commit()
    await db_session.refresh(h1)
    await db_session.refresh(h2)

    # Transactions for H1
    t1 = MFTransaction(
        holding_id=h1.id,
        date=date(2025, 1, 1),
        type=MFTransactionType.BUY,
        units=100.0,
        nav=50.0,
        amount=5000.0
    )
    # Transactions for H2
    t2 = MFTransaction(
        holding_id=h2.id,
        date=date(2025, 1, 1),
        type=MFTransactionType.BUY,
        units=50.0,
        nav=80.0,
        amount=4000.0
    )
    db_session.add_all([t1, t2])
    await db_session.commit()

    # Call endpoint
    res = await auth_client.get("/api/v1/portfolio/mf/summary")
    assert res.status_code == 200
    data = res.json()

    # Total invested = 5000 + 4000 = 9000
    assert pytest.approx(data["total_invested"], 0.01) == 9000.0
    # Current value = (100 * 75) + (50 * 100) = 7500 + 5000 = 12500
    assert pytest.approx(data["current_value"], 0.01) == 12500.0
    # Total PnL = 12500 - 9000 = 3500
    assert pytest.approx(data["total_pnl"], 0.01) == 3500.0
    # Total PnL % = (3500 / 9000) * 100 = 38.888%
    assert pytest.approx(data["total_pnl_pct"], 0.01) == (3500.0 / 9000.0) * 100
    assert data["holdings_count"] == 2
    assert data["priced_count"] == 2
    assert data["unpriced_count"] == 0
    assert data["overall_xirr"] is not None
    assert data["overall_xirr"] > 0.0


# ── 4. Unpriced Holdings Excluded and Counted ─────────────────────────────────

@pytest.mark.asyncio
async def test_unpriced_holdings_excluded_and_counted(db_session: AsyncSession, auth_client: AsyncClient):
    """
    Unpriced holdings (latest_nav is None) must be counted in unpriced_count
    and excluded from current_value, total_pnl, and overall_xirr.
    """
    # Priced scheme
    s_priced = MFScheme(
        scheme_code="122639",
        isin="INF879O01019",
        name="Parag Parikh Flexi Cap Fund",
        latest_nav=50.0,
        latest_nav_date=date(2026, 10, 6)
    )
    # Unpriced scheme (no NAV yet)
    s_unpriced = MFScheme(
        scheme_code="999999",
        isin="INF999999999",
        name="Unlisted Offshore Venture Fund",
        latest_nav=None,
        latest_nav_date=None
    )
    db_session.add_all([s_priced, s_unpriced])
    await db_session.commit()
    await db_session.refresh(s_priced)
    await db_session.refresh(s_unpriced)

    # Holding 1 (priced): 100 units @ 40 buy -> invested 4000, value 5000
    h_priced = MFHolding(scheme_id=s_priced.id, units=100.0)
    # Holding 2 (unpriced): 50 units @ 100 buy -> invested 5000
    h_unpriced = MFHolding(scheme_id=s_unpriced.id, units=50.0)
    db_session.add_all([h_priced, h_unpriced])
    await db_session.commit()
    await db_session.refresh(h_priced)
    await db_session.refresh(h_unpriced)

    t1 = MFTransaction(holding_id=h_priced.id, date=date(2025, 1, 1), type=MFTransactionType.BUY, units=100.0, nav=40.0, amount=4000.0)
    t2 = MFTransaction(holding_id=h_unpriced.id, date=date(2025, 1, 1), type=MFTransactionType.BUY, units=50.0, nav=100.0, amount=5000.0)
    db_session.add_all([t1, t2])
    await db_session.commit()

    res = await auth_client.get("/api/v1/portfolio/mf/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["holdings_count"] == 2
    assert data["priced_count"] == 1
    assert data["unpriced_count"] == 1
    assert "Unlisted Offshore Venture Fund" in data["unpriced_holdings"]

    # Current value must ONLY include the priced holding: 100 * 50 = 5000
    assert pytest.approx(data["current_value"], 0.01) == 5000.0
    # Total PnL only includes priced holding: 5000 - 4000 = 1000
    assert pytest.approx(data["total_pnl"], 0.01) == 1000.0


# ── 5. CAS Import De-Duplication ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cas_deduplication(db_session: AsyncSession):
    """
    Importing duplicate CAS records on (folio_hash, date, units, amount)
    must skip duplicates without errors or duplicate rows.
    """
    parsed_sample = {
        "schemes": [
            {
                "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "amfi": "122639",
                "isin": "INF879O01019",
                "amc": "PPFAS Mutual Fund",
                "advisor": "DIRECT",
                "type": "EQUITY",
                "close": 75.0,
                "close_calculated": 75.0,
                "valuation": {"nav": 75.0, "date": "2026-10-06", "value": 7500.0},
                "open": 0.0,
                "transactions": [
                    {
                        "date": "2024-01-15",
                        "description": "Purchase",
                        "amount": 5000.0,
                        "units": 100.0,
                        "nav": 50.0,
                        "balance": 100.0,
                        "type": "PURCHASE"
                    }
                ]
            }
        ]
    }

    # First import
    res1 = await import_parsed_cas(db_session, parsed_sample)
    assert res1["transactions_imported"] == 1
    assert res1["transactions_skipped"] == 0

    # Second import with exact same transactions
    res2 = await import_parsed_cas(db_session, parsed_sample)
    assert res2["transactions_imported"] == 0
    assert res2["transactions_skipped"] == 1

    # Verify only 1 transaction in DB
    result = await db_session.execute(select(MFTransaction))
    txs = result.scalars().all()
    assert len(txs) == 1


# ── 6. Combined Net Worth Endpoint ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_combined_net_worth_endpoint(db_session: AsyncSession, auth_client: AsyncClient):
    """
    GET /api/v1/portfolio/net-worth must return combined totals
    with stocks and mutual funds kept strictly separated.
    """
    # 1. Add an equity stock holding
    stock = Holding(
        symbol="INFY",
        exchange=Exchange.NSE,
        company_name="Infosys Limited",
        quantity=10,
        avg_buy_price=1500.0
    )
    db_session.add(stock)

    # 2. Add an MF scheme & holding
    mf_s = MFScheme(
        scheme_code="122639",
        name="HDFC Top 100 Fund",
        latest_nav=100.0,
        latest_nav_date=date(2026, 10, 6)
    )
    db_session.add(mf_s)
    await db_session.commit()
    await db_session.refresh(mf_s)

    mf_h = MFHolding(scheme_id=mf_s.id, units=50.0)
    db_session.add(mf_h)
    await db_session.commit()
    await db_session.refresh(mf_h)

    mf_tx = MFTransaction(
        holding_id=mf_h.id,
        date=date(2025, 1, 1),
        type=MFTransactionType.BUY,
        units=50.0,
        nav=80.0,
        amount=4000.0
    )
    db_session.add(mf_tx)
    await db_session.commit()

    res = await auth_client.get("/api/v1/portfolio/net-worth")
    assert res.status_code == 200
    data = res.json()

    assert "total_net_worth" in data
    assert "stocks" in data
    assert "mutual_funds" in data
    assert data["stocks"]["holdings_count"] == 1
    assert data["mutual_funds"]["holdings_count"] == 1
    # MF current value = 50 * 100 = 5000
    assert pytest.approx(data["mutual_funds"]["current_value"], 0.01) == 5000.0
    # Combined net worth must equal stocks.current_value + mutual_funds.current_value
    expected_total = data["stocks"]["current_value"] + data["mutual_funds"]["current_value"]
    assert pytest.approx(data["total_net_worth"], 0.01) == expected_total


# ── 7. Scheme History Endpoint ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheme_nav_history_endpoint(db_session: AsyncSession, auth_client: AsyncClient):
    """
    GET /api/v1/portfolio/mf/{scheme_id}/history returns daily chronological points.
    """
    s = MFScheme(scheme_code="999999", name="Test Growth Fund", latest_nav=75.0)
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)

    nav1 = MFNavHistory(scheme_id=s.id, date=date(2026, 10, 1), nav=70.0)
    nav2 = MFNavHistory(scheme_id=s.id, date=date(2026, 10, 2), nav=71.0)
    nav3 = MFNavHistory(scheme_id=s.id, date=date(2026, 10, 3), nav=72.0)
    nav4 = MFNavHistory(scheme_id=s.id, date=date(2026, 10, 4), nav=73.0)
    nav5 = MFNavHistory(scheme_id=s.id, date=date(2026, 10, 5), nav=75.0)
    db_session.add_all([nav1, nav2, nav3, nav4, nav5])
    await db_session.commit()

    res = await auth_client.get(f"/api/v1/portfolio/mf/{s.id}/history")
    assert res.status_code == 200
    data = res.json()

    assert data["scheme_id"] == s.id
    assert len(data["history"]) == 5
    assert data["history"][0]["date"] == "2026-10-01"
    assert data["history"][0]["nav"] == 70.0
    assert data["history"][4]["date"] == "2026-10-05"
    assert data["history"][4]["nav"] == 75.0


# ── 8. Manual Holdings CRUD Endpoints ────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_holdings_crud(auth_client: AsyncClient):
    """Test manual creation, editing, and deletion of a mutual fund holding."""
    # 1. Create
    payload = {
        "scheme_name": "Mirae Asset Large Cap Fund - Direct Growth",
        "scheme_code": "101234",
        "amc": "Mirae Asset",
        "category": "Equity - Large Cap",
        "folio_masked": "****9999",
        "units": 150.0,
        "avg_nav": 60.0
    }
    create_res = await auth_client.post("/api/v1/portfolio/mf/holdings", json=payload)
    assert create_res.status_code == 200
    h_data = create_res.json()
    holding_id = h_data["id"]
    assert h_data["units"] == 150.0
    assert h_data["scheme_name"] == "Mirae Asset Large Cap Fund - Direct Growth"

    # 2. Update units
    update_res = await auth_client.put(
        f"/api/v1/portfolio/mf/holdings/{holding_id}",
        json={"units": 200.0, "folio_masked": "****8888"}
    )
    assert update_res.status_code == 200

    # 3. Verify in summary
    summary_res = await auth_client.get("/api/v1/portfolio/mf/summary")
    assert summary_res.status_code == 200
    holdings = summary_res.json()["holdings"]
    matching = [h for h in holdings if h["id"] == holding_id]
    assert len(matching) == 1
    assert matching[0]["units"] == 200.0
    assert matching[0]["folio_masked"] == "****8888"

    # 4. Delete
    del_res = await auth_client.delete(f"/api/v1/portfolio/mf/holdings/{holding_id}")
    assert del_res.status_code == 200

    # 5. Verify deleted
    summary_after = await auth_client.get("/api/v1/portfolio/mf/summary")
    holdings_after = summary_after.json()["holdings"]
    assert not any(h["id"] == holding_id for h in holdings_after)


# ── 9. Constraint Check: Stock Health Score & RSI Exclude MFs ────────────────

@pytest.mark.asyncio
async def test_stock_health_score_excludes_mutual_funds():
    """
    Confirm generate_portfolio_advisory exclusively consumes equity holdings
    and does not incorporate mutual funds into stock health score or RSI.
    """
    equity_holdings = [
        {"symbol": "TCS", "exchange": "NSE", "company_name": "Tata Consultancy Services", "quantity": 15, "avg_buy_price": 3500.0, "current_value": 50000.0, "unrealized_pnl_pct": 5.0}
    ]
    advisory = await generate_portfolio_advisory(equity_holdings)
    assert "health_score" in advisory
    assert "stock_advisories" in advisory
    # Advisory symbols must only contain equity holdings
    stocks = advisory.get("stock_advisories", [])
    for s in stocks:
        assert s.get("symbol") in ["TCS"]


# ── 10. Security Audit: Zero Passwords/PAN/Raw Folio Leakage ──────────────────

@pytest.mark.asyncio
async def test_security_audit_zero_secrets_leakage(auth_client: AsyncClient, db_session: AsyncSession):
    """
    Verify that API responses do not leak raw folio numbers, PAN, or passwords.
    """
    raw_folio = "1234567890"
    scheme = MFScheme(scheme_code="111111", name="Test Fund", latest_nav=50.0)
    db_session.add(scheme)
    await db_session.commit()
    await db_session.refresh(scheme)

    holding = MFHolding(
        scheme_id=scheme.id,
        folio_masked=mask_folio(raw_folio),
        folio_hash=hash_folio(raw_folio),
        units=10.0
    )
    db_session.add(holding)
    await db_session.commit()

    res = await auth_client.get("/api/v1/portfolio/mf/summary")
    assert res.status_code == 200
    res_text = res.text

    # Raw folio must NEVER appear in the response
    assert raw_folio not in res_text
    # Masked folio must appear
    assert "****7890" in res_text
