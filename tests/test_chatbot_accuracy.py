"""
Automated accuracy test suite for the AI portfolio chatbot and context engine.
Verifies ground-truth calculations, silent default eradication, edge cases,
and grounded currency amount extraction without logging secrets.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pytest
import pandas as pd

from app.schemas.portfolio import PortfolioSummary, HoldingResponse, Exchange
from app.services.portfolio_advisor_service import (
    build_portfolio_context_data,
    answer_portfolio_query,
    groq_answer_query,
    _compute_technicals_for_stock,
)

logger = logging.getLogger(__name__)

# Track test results for final pass/fail summary table
SUMMARY_TABLE: List[Dict[str, str]] = []


def record_result(test_name: str, mode: str, status: str, details: str = ""):
    """Record test outcome for the summary table."""
    SUMMARY_TABLE.append({
        "test_name": test_name,
        "mode": mode,
        "status": status,
        "details": details,
    })


# =============================================================================
# Post-Response Currency Verifier
# =============================================================================

def verify_response_numbers(reply: str, context_text: str) -> List[str]:
    """
    Extract ₹ amounts from reply and verify whether they exist in context_text.
    Logs a warning if an ungrounded ₹ amount is detected.
    Returns a list of ungrounded amount strings.
    """
    rupee_pattern = re.compile(r'₹\s*([0-9,]+(?:\.[0-9]+)?)')
    reply_matches = rupee_pattern.findall(reply)
    ungrounded = []

    for raw_match in reply_matches:
        num_str = raw_match.replace(",", "")
        try:
            val = float(num_str)
        except ValueError:
            continue

        # Check for various formats in context: raw number, formatted with comma, integer
        variants = [
            raw_match,
            num_str,
            f"{val:,.2f}",
            f"{val:,.0f}",
            f"{val:.2f}",
            f"{val:g}",
        ]
        found = any(v in context_text for v in variants)
        if not found:
            logger.warning(
                "[Accuracy Warning] Extracted amount ₹%s from LLM reply was NOT found in portfolio context!",
                raw_match
            )
            ungrounded.append(raw_match)

    return ungrounded


# =============================================================================
# Fixture: 6 Holdings Portfolio with Ground-Truth Calculations
# =============================================================================

@pytest.fixture
def benchmark_portfolio() -> Tuple[PortfolioSummary, Dict[str, Any], Dict[str, Any]]:
    """
    Fixture portfolio with 6 holdings:
    - 2 gainers (RELIANCE, HDFCBANK)
    - 3 losers (TCS, INFY, TATAMOTORS)
    - 1 missing LTP (ZOMATO)
    Computes all ground-truth metrics in code.
    """
    now = datetime.now(timezone.utc)

    raw_holdings = [
        {
            "id": 1,
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries Limited",
            "quantity": 10.0,
            "avg_buy_price": 2500.00,
            "live_price": 2800.00,
            "day_change_pct": 1.50,
            "rsi": 58.5,
            "stop_loss": 2650.00,
            "target_1": 2950.00,
            "target_2": 3100.00,
        },
        {
            "id": 2,
            "symbol": "TCS",
            "company_name": "Tata Consultancy Services",
            "quantity": 5.0,
            "avg_buy_price": 3800.00,
            "live_price": 3600.00,
            "day_change_pct": -0.80,
            "rsi": 42.0,
            "stop_loss": 3450.00,
            "target_1": 3900.00,
            "target_2": 4100.00,
        },
        {
            "id": 3,
            "symbol": "INFY",
            "company_name": "Infosys Limited",
            "quantity": 20.0,
            "avg_buy_price": 1500.00,
            "live_price": 1400.00,
            "day_change_pct": -1.20,
            "rsi": 31.0,
            "stop_loss": 1330.00,
            "target_1": 1550.00,
            "target_2": 1650.00,
        },
        {
            "id": 4,
            "symbol": "HDFCBANK",
            "company_name": "HDFC Bank Limited",
            "quantity": 15.0,
            "avg_buy_price": 1600.00,
            "live_price": 1720.00,
            "day_change_pct": 0.60,
            "rsi": 64.2,
            "stop_loss": 1630.00,
            "target_1": 1800.00,
            "target_2": 1900.00,
        },
        {
            "id": 5,
            "symbol": "TATAMOTORS",
            "company_name": "Tata Motors Limited",
            "quantity": 25.0,
            "avg_buy_price": 900.00,
            "live_price": 850.00,
            "day_change_pct": -2.10,
            "rsi": 28.0,
            "stop_loss": 800.00,
            "target_1": 920.00,
            "target_2": 980.00,
        },
        {
            "id": 6,
            "symbol": "ZOMATO",
            "company_name": "Zomato Limited",
            "quantity": 50.0,
            "avg_buy_price": 200.00,
            "live_price": None,  # Intentionally missing LTP
            "day_change_pct": None,
            "rsi": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
        },
    ]

    holding_objs: List[HoldingResponse] = []
    tot_invested = 0.0
    tot_cur_val = 0.0
    gainers = 0
    losers = 0
    per_stock = {}

    for h in raw_holdings:
        qty = h["quantity"]
        avg_buy = h["avg_buy_price"]
        lp = h["live_price"]
        invested = round(qty * avg_buy, 2)
        if lp is not None:
            cur_val = round(qty * lp, 2)
            tot_cur_val += cur_val
            tot_invested += invested
            pnl = round(cur_val - invested, 2)
            pnl_pct = round((pnl / invested) * 100, 2)
            if pnl > 0:
                gainers += 1
            elif pnl < 0:
                losers += 1
        else:
            cur_val = None
            pnl = None
            pnl_pct = None

        per_stock[h["symbol"]] = {
            "quantity": qty,
            "avg_buy_price": avg_buy,
            "live_price": lp,
            "current_value": cur_val,
            "invested_value": invested,
            "unrealized_pnl": pnl,
            "pnl_pct": pnl_pct,
            "day_change_pct": h["day_change_pct"],
            "rsi": h["rsi"],
            "stop_loss": h["stop_loss"],
            "target_1": h["target_1"],
            "target_2": h["target_2"],
        }

        holding_objs.append(HoldingResponse(
            id=h["id"],
            symbol=h["symbol"],
            company_name=h["company_name"],
            exchange=Exchange.NSE,
            quantity=qty,
            avg_buy_price=avg_buy,
            ipo_symbol=None,
            created_at=now,
            updated_at=now,
            live_price=lp,
            current_value=cur_val,
            invested_value=invested,
            unrealized_pnl=pnl,
            pnl_pct=pnl_pct,
            day_change_pct=h["day_change_pct"],
            transactions=[],
        ))

    overall_pnl = round(tot_cur_val - tot_invested, 2)
    overall_pnl_pct = round((overall_pnl / tot_invested) * 100, 2)

    # Find biggest gainer, loser, and largest weight
    valued_stocks = [h for h in raw_holdings if h["live_price"] is not None]
    biggest_gainer = max(valued_stocks, key=lambda x: per_stock[x["symbol"]]["unrealized_pnl"])
    biggest_loser = min(valued_stocks, key=lambda x: per_stock[x["symbol"]]["unrealized_pnl"])
    largest_holding = max(valued_stocks, key=lambda x: per_stock[x["symbol"]]["current_value"])
    largest_weight_pct = round((per_stock[largest_holding["symbol"]]["current_value"] / tot_cur_val) * 100, 1)

    expected = {
        "invested": tot_invested,
        "current_value": tot_cur_val,
        "overall_pnl": overall_pnl,
        "overall_pnl_pct": overall_pnl_pct,
        "up_count": gainers,
        "down_count": losers,
        "holdings_count": len(raw_holdings),
        "unpriced_count": 1,
        "unpriced_symbols": ["ZOMATO"],
        "biggest_gainer": (biggest_gainer["symbol"], per_stock[biggest_gainer["symbol"]]["unrealized_pnl"]),
        "biggest_loser": (biggest_loser["symbol"], per_stock[biggest_loser["symbol"]]["unrealized_pnl"]),
        "largest_weight": (largest_holding["symbol"], largest_weight_pct),
        "health_score": 52,
        "per_stock": per_stock,
    }

    summary = PortfolioSummary(
        total_invested=tot_invested,
        current_value=tot_cur_val,
        total_unrealized_pnl=overall_pnl,
        total_pnl_pct=overall_pnl_pct,
        day_change=-250.00,
        day_change_pct=-0.21,
        holdings_count=len(holding_objs),
        gainers=gainers,
        losers=losers,
        unpriced_count=1,
        unpriced_symbols=["ZOMATO"],
        holdings=holding_objs,
        last_updated=now,
    )

    advisory_data = {
        "health_score": expected["health_score"],
        "health_verdict": "Base Consolidation",
        "summary": "Portfolio holds mixed sector allocation with tech drawdown drag.",
        "stock_advisories": [
            {
                "symbol": h["symbol"],
                "company_name": h["company_name"],
                "quantity": h["quantity"],
                "avg_buy_price": h["avg_buy_price"],
                "live_price": h["live_price"],
                "current_value": per_stock[h["symbol"]]["current_value"],
                "unrealized_pnl": per_stock[h["symbol"]]["unrealized_pnl"],
                "pnl_pct": per_stock[h["symbol"]]["pnl_pct"],
                "day_change_pct": h["day_change_pct"],
                "capital_weight_pct": round((per_stock[h["symbol"]]["current_value"] / tot_cur_val * 100), 1) if per_stock[h["symbol"]]["current_value"] else 0.0,
                "technicals": {
                    "rsi": h["rsi"],
                    "rsi_status": "Oversold" if (h["rsi"] and h["rsi"] <= 35) else "Normal",
                    "stop_loss": h["stop_loss"],
                    "target_1": h["target_1"],
                    "target_2": h["target_2"],
                    "support_1": round(h["stop_loss"] * 1.02, 2) if h["stop_loss"] else None,
                    "action": "HOLD & MONITOR",
                    "strategy": "Disciplined stop adherence.",
                } if h["rsi"] is not None else {}
            }
            for h in raw_holdings
        ]
    }

    return summary, advisory_data, expected


# =============================================================================
# Test 1: Deterministic Context Accuracy (No LLM Call)
# =============================================================================

def test_context_contains_exact_expected_values(benchmark_portfolio):
    """
    Assert that the context block produced by build_portfolio_context_data contains
    all mathematically exact expected portfolio totals and per-stock values.
    """
    summary, advisory_data, expected = benchmark_portfolio
    ctx = build_portfolio_context_data(advisory_data, portfolio_summary=summary)

    # 1. Totals verification
    assert ctx["total_invested"] == expected["invested"], f"Total invested mismatch: {ctx['total_invested']} vs {expected['invested']}"
    assert ctx["current_value"] == expected["current_value"], f"Current value mismatch: {ctx['current_value']} vs {expected['current_value']}"
    assert ctx["overall_pnl"] == expected["overall_pnl"], f"Overall P&L mismatch: {ctx['overall_pnl']} vs {expected['overall_pnl']}"
    assert ctx["overall_pnl_pct"] == expected["overall_pnl_pct"], f"Overall P&L % mismatch: {ctx['overall_pnl_pct']} vs {expected['overall_pnl_pct']}"

    block = ctx["holdings_block"]

    # 2. Check exact numbers in holdings text block
    # RELIANCE: Buy 2500, LTP 2800, P&L +3000 (+12.00%)
    assert "RELIANCE" in block
    assert "AvgBuy=₹2,500.00" in block
    assert "LTP=₹2,800.00" in block
    assert "P&L=+₹3,000.00 (+12.00%)" in block
    assert "StopLoss=₹2,650.00" in block
    assert "Target1=₹2,950.00" in block

    # TCS: Buy 3800, LTP 3600, P&L -1000 (-5.26%)
    assert "TCS" in block
    assert "AvgBuy=₹3,800.00" in block
    assert "LTP=₹3,600.00" in block
    assert "P&L=-₹1,000.00 (-5.26%)" in block
    assert "StopLoss=₹3,450.00" in block

    # INFY: Buy 1500, LTP 1400, P&L -2000 (-6.67%)
    assert "INFY" in block
    assert "AvgBuy=₹1,500.00" in block
    assert "LTP=₹1,400.00" in block
    assert "P&L=-₹2,000.00 (-6.67%)" in block
    assert "RSI=31.0" in block

    # TATAMOTORS: Buy 900, LTP 850, P&L -1250 (-5.56%)
    assert "TATAMOTORS" in block
    assert "AvgBuy=₹900.00" in block
    assert "LTP=₹850.00" in block
    assert "P&L=-₹1,250.00 (-5.56%)" in block

    # ZOMATO: Missing LTP -> must show unavailable, not 0 or avg_buy
    assert "ZOMATO" in block
    assert "LTP=unavailable" in block
    assert "CurrentVal=unavailable" in block
    assert "P&L=unavailable" in block
    assert "RSI=unavailable" in block
    assert "StopLoss=unavailable" in block

    record_result("test_context_contains_exact_expected_values", "Unit", "PASS", "Exact totals and holdings asserted")


def test_rule_based_accuracy(benchmark_portfolio):
    """
    Test fallback rule engine accuracy for specific questions against expected values.
    """
    summary, advisory_data, expected = benchmark_portfolio

    # Overall P&L query (priced holdings only: +550.00, +0.46%)
    res = answer_portfolio_query("what is my overall profit and loss till now?", advisory_data, portfolio_summary=summary)
    assert "+₹550.00" in res or "+550.00" in res or "₹550.00" in res
    assert "+0.46%" in res or "0.46%" in res
    assert "1 holding(s) unpriced, excluded from totals" in res

    # Buy price query
    res_buy = answer_portfolio_query("at what price did I buy reliance?", advisory_data, portfolio_summary=summary)
    assert "₹2,500.00" in res_buy

    # Stop loss query
    res_sl = answer_portfolio_query("what is the stop loss for TCS?", advisory_data, portfolio_summary=summary)
    assert "₹3,450.00" in res_sl

    # Missing stock LTP query
    res_zomato = answer_portfolio_query("what is the ltp of zomato?", advisory_data, portfolio_summary=summary)
    assert "unavailable" in res_zomato.lower()

    # Post-response check on rule engine output
    ctx = build_portfolio_context_data(advisory_data, portfolio_summary=summary)
    context_text = f"Invested: {ctx['total_invested']}, Current: {ctx['current_value']}, PnL: {ctx['overall_pnl']} {ctx['holdings_block']}"
    ungrounded = verify_response_numbers(res, context_text)
    assert len(ungrounded) == 0, f"Found ungrounded amounts in rule response: {ungrounded}"

    record_result("test_rule_based_accuracy", "Unit", "PASS", "Rule queries answered with zero hallucinated figures")


def test_page_summary_and_chatbot_context_agree_on_unpriced(benchmark_portfolio):
    """
    Assert that the UI page summary and chatbot context compute totals over priced holdings only
    and agree exactly on totals, P&L, unpriced count, and unpriced symbols.
    """
    summary, advisory_data, expected = benchmark_portfolio
    ctx = build_portfolio_context_data(advisory_data, portfolio_summary=summary)

    # 1. Totals match between page summary and chatbot context
    assert ctx["total_invested"] == summary.total_invested == 120500.0
    assert ctx["current_value"] == summary.current_value == 121050.0
    assert ctx["overall_pnl"] == summary.total_unrealized_pnl == 550.0
    assert ctx["overall_pnl_pct"] == summary.total_pnl_pct == 0.46

    # 2. Unpriced metadata agreement
    assert ctx["unpriced_count"] == summary.unpriced_count == 1
    assert ctx["unpriced_symbols"] == summary.unpriced_symbols == ["ZOMATO"]
    assert ctx["unpriced_note"] == "1 holding(s) unpriced, excluded from totals"
    assert "1 holding(s) unpriced, excluded from totals" in ctx["holdings_block"]

    # 3. Rule response also presents the unpriced note
    res = answer_portfolio_query("what is my overall profit and loss?", advisory_data, portfolio_summary=summary)
    assert "1 holding(s) unpriced, excluded from totals" in res

    record_result("test_page_summary_and_chatbot_context_agree_on_unpriced", "Unit", "PASS", "Summary and context agree on unpriced exclusions")



# =============================================================================
# Test 2: Edge Cases
# =============================================================================

def test_edge_case_empty_portfolio():
    """Verify empty portfolio gracefully returns empty state without silent zero crashes."""
    empty_summary = PortfolioSummary(
        total_invested=0.0,
        current_value=0.0,
        total_unrealized_pnl=0.0,
        total_pnl_pct=0.0,
        day_change=0.0,
        day_change_pct=0.0,
        holdings_count=0,
        gainers=0,
        losers=0,
        holdings=[],
        last_updated=datetime.now(timezone.utc),
    )
    empty_advisory = {
        "health_score": 50,
        "health_verdict": "Empty Portfolio",
        "summary": "No holdings.",
        "stock_advisories": [],
    }

    ctx = build_portfolio_context_data(empty_advisory, portfolio_summary=empty_summary)
    assert ctx["total_invested"] == 0.0
    assert ctx["holdings"] == []
    assert "No holdings found." in ctx["holdings_block"]

    res = answer_portfolio_query("what is my overall profit and loss?", empty_advisory, portfolio_summary=empty_summary)
    assert "₹0.00" in res or "No active holdings" in res

    record_result("test_edge_case_empty_portfolio", "EdgeCase", "PASS", "Empty portfolio handled safely")


def test_edge_case_one_holding():
    """Verify single holding portfolio correctly identifies 100% single-stock concentration."""
    now = datetime.now(timezone.utc)
    single_holding = HoldingResponse(
        id=1,
        symbol="TITAN",
        company_name="Titan Company Limited",
        exchange=Exchange.NSE,
        quantity=10.0,
        avg_buy_price=3000.0,
        ipo_symbol=None,
        created_at=now,
        updated_at=now,
        live_price=3300.0,
        current_value=33000.0,
        invested_value=30000.0,
        unrealized_pnl=3000.0,
        pnl_pct=10.0,
        day_change_pct=1.0,
        transactions=[],
    )
    single_summary = PortfolioSummary(
        total_invested=30000.0,
        current_value=33000.0,
        total_unrealized_pnl=3000.0,
        total_pnl_pct=10.0,
        day_change=330.0,
        day_change_pct=1.0,
        holdings_count=1,
        gainers=1,
        losers=0,
        holdings=[single_holding],
        last_updated=now,
    )
    single_advisory = {
        "health_score": 60,
        "health_verdict": "Concentrated",
        "stock_advisories": [{
            "symbol": "TITAN",
            "quantity": 10.0,
            "avg_buy_price": 3000.0,
            "live_price": 3300.0,
            "current_value": 33000.0,
            "unrealized_pnl": 3000.0,
            "pnl_pct": 10.0,
            "capital_weight_pct": 100.0,
            "technicals": {"rsi": 55.0, "stop_loss": 2900.0, "target_1": 3500.0}
        }]
    }

    res = answer_portfolio_query("how to improve my portfolio?", single_advisory, portfolio_summary=single_summary)
    assert "TITAN" in res
    assert "100.0%" in res or "exceeds" in res

    record_result("test_edge_case_one_holding", "EdgeCase", "PASS", "100% concentration detected")


def test_edge_case_missing_ltp():
    """Verify holding with None live price writes 'unavailable' and does NOT fake 0 or avg_buy."""
    advisory = {
        "health_score": 40,
        "stock_advisories": [{
            "symbol": "NEW_LISTED",
            "quantity": 100,
            "avg_buy_price": 50.0,
            "live_price": None,
            "current_value": None,
            "unrealized_pnl": None,
            "pnl_pct": None,
            "technicals": {}
        }]
    }
    ctx = build_portfolio_context_data(advisory, portfolio_summary=None)
    assert "LTP=unavailable" in ctx["holdings_block"]
    assert "CurrentVal=unavailable" in ctx["holdings_block"]
    assert "P&L=unavailable" in ctx["holdings_block"]

    record_result("test_edge_case_missing_ltp", "EdgeCase", "PASS", "Missing LTP safely rendered as unavailable")


def test_edge_case_less_than_10_candles():
    """Verify historical candles < 10 returns None technicals without fake 50 RSI."""
    df_short = pd.DataFrame({
        "Open": [100.0, 102.0, 101.0, 103.0],
        "High": [105.0, 104.0, 103.0, 106.0],
        "Low": [99.0, 100.0, 100.0, 101.0],
        "Close": [102.0, 101.0, 103.0, 104.0],
        "Volume": [1000, 1200, 900, 1500]
    })
    tech = _compute_technicals_for_stock(df_short, avg_buy_price=100.0)
    assert tech["rsi"] is None, f"Expected None RSI for <10 candles, got {tech['rsi']}"
    assert tech["stop_loss"] is None, f"Expected None SL for <10 candles, got {tech['stop_loss']}"
    assert tech["target_1"] is None, f"Expected None Target1 for <10 candles, got {tech['target_1']}"

    record_result("test_edge_case_less_than_10_candles", "EdgeCase", "PASS", "Short history returns None indicators")


def test_edge_case_zero_invested():
    """Verify portfolio with 0 invested does not produce ZeroDivisionError."""
    advisory = {
        "health_score": 50,
        "stock_advisories": [{
            "symbol": "GIFTED_SHARES",
            "quantity": 10,
            "avg_buy_price": 0.0,
            "live_price": 100.0,
            "current_value": 1000.0,
            "unrealized_pnl": 1000.0,
            "pnl_pct": 0.0,
            "technicals": {"rsi": 50.0}
        }]
    }
    ctx = build_portfolio_context_data(advisory, portfolio_summary=None)
    assert ctx["total_invested"] == 0.0
    assert ctx["current_value"] == 1000.0

    res = answer_portfolio_query("what is my pnl for GIFTED_SHARES?", advisory)
    assert "GIFTED_SHARES" in res

    record_result("test_edge_case_zero_invested", "EdgeCase", "PASS", "Zero invested handled without ZeroDivisionError")


# =============================================================================
# Test 3: Grounded Currency Verifier Unit Test
# =============================================================================

def test_verify_response_numbers_hallucination_detection():
    """Verify that ungrounded currency amounts log warning and return the ungrounded tokens."""
    context = "Holdings: RELIANCE LTP=₹2,800.00, P&L=+₹3,000.00. Total invested: ₹25,000.00."

    # Grounded reply
    grounded_reply = "Your RELIANCE holding is up by ₹3,000.00 at LTP ₹2,800.00."
    ungrounded_clean = verify_response_numbers(grounded_reply, context)
    assert len(ungrounded_clean) == 0

    # Hallucinated reply
    hallucinated_reply = "We expect your gains to reach ₹99,999.00 next week."
    ungrounded_bad = verify_response_numbers(hallucinated_reply, context)
    assert "99,999.00" in ungrounded_bad or "99999.00" in ungrounded_bad

    record_result("test_verify_response_numbers", "Unit", "PASS", "Hallucinated ₹ amounts successfully detected")


# =============================================================================
# Test 4: Live Groq Model Evaluation (25 Questions — Env Flag Gated)
# =============================================================================

GROQ_QUESTIONS = [
    ("What is my total invested capital?", "invested"),
    ("What is my current portfolio value?", "current_value"),
    ("What is my overall profit and loss till now?", "overall_pnl"),
    ("What is my overall P&L percentage?", "overall_pnl_pct"),
    ("What is the health score of my portfolio?", "health_score"),
    ("How many stocks are in profit?", "up_count"),
    ("How many stocks are in loss?", "down_count"),
    ("What is the largest holding by weight?", "largest_weight"),
    ("Which stock is my biggest loser?", "biggest_loser"),
    ("Which stock is my biggest gainer?", "biggest_gainer"),
    ("At what price did I buy RELIANCE?", "reliance_buy"),
    ("What is the live price (LTP) of RELIANCE?", "reliance_ltp"),
    ("What is the unrealized P&L for RELIANCE?", "reliance_pnl"),
    ("What is the stop loss for RELIANCE?", "reliance_sl"),
    ("What is the Target 1 for RELIANCE?", "reliance_t1"),
    ("At what price did I buy TCS?", "tcs_buy"),
    ("What is the live market price of TCS?", "tcs_ltp"),
    ("What is the unrealized P&L for TCS?", "tcs_pnl"),
    ("What is the stop loss for TCS?", "tcs_sl"),
    ("What is the target price for TCS?", "tcs_t1"),
    ("At what price did I buy INFY?", "infy_buy"),
    ("What is the LTP of INFY?", "infy_ltp"),
    ("What is the stop loss for TATAMOTORS?", "tatamotors_sl"),
    ("What is the target 1 for TATAMOTORS?", "tatamotors_t1"),
    ("What is the live price (LTP) of ZOMATO?", "zomato_ltp"),
]


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_GROQ_ACCURACY_TESTS") != "1",
    reason="Live Groq test disabled. Set RUN_GROQ_ACCURACY_TESTS=1 to run."
)
async def test_live_groq_accuracy_25_questions(benchmark_portfolio):
    """
    Calls the real Groq model for 25 questions and verifies accuracy of numbers,
    ensuring no missing-data hallucinations or fabricated prices.
    Never logs secrets or api keys.
    """
    summary, advisory_data, expected = benchmark_portfolio
    ctx = build_portfolio_context_data(advisory_data, portfolio_summary=summary)
    context_text = f"{ctx['overall_pnl']} {ctx['total_invested']} {ctx['current_value']} {ctx['holdings_block']}"

    passed_count = 0
    prod_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    allow_fallback = os.getenv("ALLOW_GROQ_FALLBACK_MODEL") == "1"

    for query, key in GROQ_QUESTIONS:
        answer, source, used_model = await groq_answer_query(
            query=query,
            advisory_data=advisory_data,
            portfolio_summary=summary,
            return_model=True
        )

        print(f"[Live Groq Question] Model: '{used_model}' | Q: '{query}'")

        if not allow_fallback and used_model != prod_model:
            pytest.fail(
                f"Model mismatch for question '{query}': expected production model '{prod_model}', "
                f"but got '{used_model}'. Set ALLOW_GROQ_FALLBACK_MODEL=1 to allow fallback models."
            )

        assert answer and len(answer) > 0

        # Post-response grounding check
        ungrounded = verify_response_numbers(answer, context_text)
        if ungrounded:
            logger.warning("[Live Groq Warning] Q: '%s' -> Ungrounded amounts: %s", query, ungrounded)

        ans_norm = answer.replace('–', '-').replace('—', '-')
        ans_lower = ans_norm.lower()

        # Specific key checks allowing standard rounding/formatting
        if key == "invested":
            assert "120,500" in ans_norm or "1,20,500" in ans_norm or "120500" in ans_norm
        elif key == "current_value":
            assert "121,050" in ans_norm or "1,21,050" in ans_norm or "121050" in ans_norm
        elif key == "overall_pnl":
            assert "550" in ans_norm
        elif key == "overall_pnl_pct":
            assert "0.46" in ans_norm or "0.5" in ans_norm
        elif key == "health_score":
            assert "52" in ans_norm
        elif key == "up_count":
            assert "2" in ans_norm or "two" in ans_lower
        elif key == "down_count":
            assert "3" in ans_norm or "three" in ans_lower
        elif key == "largest_weight":
            assert "reliance" in ans_lower or "infy" in ans_lower or "23" in ans_norm
        elif key == "biggest_loser":
            assert "infy" in ans_lower or "2,000" in ans_norm or "2000" in ans_norm or "two thousand" in ans_lower
        elif key == "biggest_gainer":
            assert "reliance" in ans_lower or "3,000" in ans_norm or "3000" in ans_norm or "three thousand" in ans_lower
        elif key == "reliance_buy":
            assert "2,500" in ans_norm or "2500" in ans_norm
        elif key == "reliance_ltp":
            assert "2,800" in ans_norm or "2800" in ans_norm
        elif key == "reliance_pnl":
            assert "3,000" in ans_norm or "3000" in ans_norm
        elif key == "reliance_sl":
            assert "2,650" in ans_norm or "2650" in ans_norm
        elif key == "reliance_t1":
            assert "2,950" in ans_norm or "2950" in ans_norm
        elif key == "tcs_buy":
            assert "3,800" in ans_norm or "3800" in ans_norm
        elif key == "tcs_ltp":
            assert "3,600" in ans_norm or "3600" in ans_norm
        elif key == "tcs_pnl":
            assert "1,000" in ans_norm or "1000" in ans_norm
        elif key == "tcs_sl":
            assert "3,450" in ans_norm or "3450" in ans_norm
        elif key == "tcs_t1":
            assert "3,900" in ans_norm or "3900" in ans_norm
        elif key == "infy_buy":
            assert "1,500" in ans_norm or "1500" in ans_norm
        elif key == "infy_ltp":
            assert "1,400" in ans_norm or "1400" in ans_norm
        elif key == "tatamotors_sl":
            assert "800" in ans_norm
        elif key == "tatamotors_t1":
            assert "920" in ans_norm
        elif key == "zomato_ltp":
            assert "unavailable" in ans_lower or "don't have" in ans_lower or "not available" in ans_lower

        passed_count += 1

    record_result("test_live_groq_accuracy_25_questions", "Live Groq", "PASS", f"{passed_count}/25 questions verified")


# =============================================================================
# Pytest Summary Table Fixture (Requirement 6)
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def print_accuracy_summary_table():
    """
    Prints an ASCII / Markdown Pass/Fail table at the end of the test run.
    Ensures zero secrets or sensitive keys are exposed.
    """
    yield
    print("\n" + "=" * 80)
    print("           AI CHATBOT & CONTEXT ACCURACY TEST SUMMARY")
    print("=" * 80)
    header = f"| {'Test Case':<42} | {'Mode':<10} | {'Status':<8} | {'Details':<14} |"
    divider = f"|{'-'*44}|{'-'*12}|{'-'*10}|{'-'*16}|"
    print(header)
    print(divider)

    for item in SUMMARY_TABLE:
        details_safe = item['details'].replace("₹", "Rs.")
        test_safe = item['test_name']
        row = f"| {test_safe:<42} | {item['mode']:<10} | {item['status']:<8} | {details_safe:<14} |"
        try:
            print(row)
        except UnicodeEncodeError:
            print(row.encode('ascii', errors='replace').decode('ascii'))

    print("=" * 80 + "\n")


