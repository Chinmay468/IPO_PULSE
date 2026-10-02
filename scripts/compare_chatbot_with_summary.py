#!/usr/bin/env python3
"""
CLI Evaluation Script: Compare AI Chatbot Answers with /portfolio/summary Data.
Queries the real portfolio summary and asks 25 questions to verify that the
chatbot answers are mathematically and contextually consistent with the summary endpoint.

Security Note: Never logs or prints credentials, tokens, or API keys.
"""

import sys
import os
import re
import argparse
import asyncio
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.auth import create_access_token


QUESTIONS = [
    ("What is my total invested capital?", "total_invested"),
    ("What is my current portfolio value?", "current_value"),
    ("What is my overall profit and loss till now?", "overall_pnl"),
    ("What is my overall P&L percentage?", "overall_pnl_pct"),
    ("What is the health score of my portfolio?", "health_score"),
    ("How many stocks are in profit?", "gainers"),
    ("How many stocks are in loss?", "losers"),
    ("What is the largest holding by weight?", "largest_weight"),
    ("Which stock is my biggest loser?", "biggest_loser"),
    ("Which stock is my biggest gainer?", "biggest_gainer"),
    ("At what price did I buy RELIANCE?", "RELIANCE_buy"),
    ("What is the live price (LTP) of RELIANCE?", "RELIANCE_ltp"),
    ("What is the unrealized P&L for RELIANCE?", "RELIANCE_pnl"),
    ("What is the stop loss for RELIANCE?", "RELIANCE_sl"),
    ("What is the Target 1 for RELIANCE?", "RELIANCE_t1"),
    ("At what price did I buy TCS?", "TCS_buy"),
    ("What is the live market price of TCS?", "TCS_ltp"),
    ("What is the unrealized P&L for TCS?", "TCS_pnl"),
    ("What is the stop loss for TCS?", "TCS_sl"),
    ("What is the target price for TCS?", "TCS_t1"),
    ("At what price did I buy INFY?", "INFY_buy"),
    ("What is the LTP of INFY?", "INFY_ltp"),
    ("What is the stop loss for TATAMOTORS?", "TATAMOTORS_sl"),
    ("What is the target 1 for TATAMOTORS?", "TATAMOTORS_t1"),
    ("What is the live price (LTP) of ZOMATO?", "ZOMATO_ltp"),
]


def _format_curr(val: Optional[float]) -> str:
    if val is None:
        return "unavailable"
    return f"Rs.{val:,.2f}"


def _get_auth_header() -> Dict[str, str]:
    """Generates an internal bearer token without printing or leaking secrets."""
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


async def fetch_summary_http(client: httpx.AsyncClient, base_url: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/portfolio/summary"
    resp = await client.get(url, headers=_get_auth_header())
    resp.raise_for_status()
    return resp.json()


async def ask_question_http(client: httpx.AsyncClient, base_url: str, question: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/portfolio/advisory/ask"
    resp = await client.post(url, json={"query": question}, headers=_get_auth_header())
    resp.raise_for_status()
    return resp.json()


async def fetch_summary_direct() -> Tuple[Dict[str, Any], Any]:
    from app.database import AsyncSessionLocal, init_db
    from app.services import portfolio_service as svc
    from app.services.portfolio_advisor_service import generate_portfolio_advisory

    await init_db()
    async with AsyncSessionLocal() as db:
        summary_obj = await svc.get_portfolio_summary(db)
        advisory_data = await generate_portfolio_advisory(db)
        summary_dict = summary_obj.model_dump() if hasattr(summary_obj, "model_dump") else summary_obj.__dict__
        return summary_dict, advisory_data


async def ask_question_direct(advisory_data: dict, summary_dict: dict, question: str) -> Dict[str, Any]:
    from app.services.portfolio_advisor_service import groq_answer_query

    answer, source, model = await groq_answer_query(
        query=question,
        advisory_data=advisory_data,
        portfolio_summary=summary_dict,
        return_model=True
    )
    return {"query": question, "answer": answer, "source": source, "model": model}


def extract_expected_metric(key: str, summary: Dict[str, Any]) -> str:
    holdings = summary.get("holdings", [])
    holdings_by_sym = {h.get("symbol", "").upper(): h for h in holdings}

    if key == "total_invested":
        return _format_curr(summary.get("total_invested"))
    elif key == "current_value":
        return _format_curr(summary.get("current_value"))
    elif key == "overall_pnl":
        pnl = summary.get("total_unrealized_pnl")
        return _format_curr(pnl) if pnl is not None else "unavailable"
    elif key == "overall_pnl_pct":
        pct = summary.get("total_pnl_pct")
        return f"{pct:.2f}%" if pct is not None else "unavailable"
    elif key == "health_score":
        return "Advisory score (0-100)"
    elif key == "gainers":
        return f"{summary.get('gainers', 0)} stocks"
    elif key == "losers":
        return f"{summary.get('losers', 0)} stocks"
    elif key == "largest_weight":
        if holdings:
            valid = [h for h in holdings if h.get("current_value") is not None]
            if valid:
                top = max(valid, key=lambda x: x.get("current_value", 0))
                return f"{top.get('symbol')} ({_format_curr(top.get('current_value'))})"
        return "N/A"
    elif key == "biggest_gainer":
        if holdings:
            valid = [h for h in holdings if h.get("unrealized_pnl") is not None]
            if valid:
                top = max(valid, key=lambda x: x.get("unrealized_pnl", 0))
                return f"{top.get('symbol')} ({_format_curr(top.get('unrealized_pnl'))})"
        return "N/A"
    elif key == "biggest_loser":
        if holdings:
            valid = [h for h in holdings if h.get("unrealized_pnl") is not None]
            if valid:
                bot = min(valid, key=lambda x: x.get("unrealized_pnl", 0))
                return f"{bot.get('symbol')} ({_format_curr(bot.get('unrealized_pnl'))})"
        return "N/A"
    elif "_" in key:
        sym, metric = key.split("_", 1)
        h = holdings_by_sym.get(sym)
        if not h:
            return f"{sym} not in portfolio"
        if metric == "buy":
            return _format_curr(h.get("avg_buy_price"))
        elif metric == "ltp":
            return _format_curr(h.get("live_price"))
        elif metric == "pnl":
            return _format_curr(h.get("unrealized_pnl"))
        elif metric == "sl":
            return "Advisory StopLoss level"
        elif metric == "t1":
            return "Advisory Target 1"

    return "N/A"


def check_consistency(expected_str: str, answer_text: str) -> str:
    """Check if key numerical information from expected_str appears in answer_text."""
    if not answer_text:
        return "EMPTY"

    ans_norm = answer_text.replace("₹", "Rs.").replace(",", "")
    exp_norm = expected_str.replace("₹", "Rs.").replace(",", "")

    # Look for unpriced / unavailable signals
    if "unavailable" in exp_norm.lower() or "not in portfolio" in exp_norm.lower():
        if any(w in answer_text.lower() for w in ["unavailable", "don't have", "not available", "excluded", "unpriced"]):
            return "MATCH (unavailable acknowledged)"
        return "CHECK"

    # Extract numbers from expected_str
    numbers = re.findall(r'[-+]?\d*\.?\d+', exp_norm)
    if not numbers:
        return "INFO"

    matches = [n for n in numbers if n in ans_norm]
    if len(matches) > 0:
        return f"MATCH ({matches[0]})"

    return "REVIEW"


async def main():
    parser = argparse.ArgumentParser(description="Compare AI Chatbot answers with /portfolio/summary")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of the running API")
    parser.add_argument("--direct", action="store_true", help="Direct DB access mode (bypasses HTTP)")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP request timeout in seconds")
    args = parser.parse_args()

    print("=" * 88)
    print("        PORTFOLIO AI CHATBOT ACCURACY & SUMMARY COMPARISON SUITE")
    print("=" * 88)

    summary: Dict[str, Any] = {}
    advisory_data: Optional[Dict[str, Any]] = None
    use_direct = args.direct

    if not use_direct:
        try:
            async with httpx.AsyncClient(timeout=args.timeout) as client:
                summary = await fetch_summary_http(client, args.url)
                print(f"[Mode] Connected to HTTP server at {args.url}")
        except Exception as exc:
            print(f"[Warning] HTTP connection failed ({type(exc).__name__}). Falling back to Direct DB mode.")
            use_direct = True

    if use_direct:
        summary, advisory_data = await fetch_summary_direct()
        print("[Mode] Running via Direct Database & In-Process Service pipeline.")

    # Print summary highlights
    unpriced_cnt = summary.get("unpriced_count", 0)
    unpriced_syms = summary.get("unpriced_symbols", [])
    unpriced_str = f" | Unpriced Excluded: {unpriced_cnt} ({', '.join(unpriced_syms)})" if unpriced_cnt > 0 else ""
    print(f"\n[Summary Baseline]")
    print(f"Invested: {_format_curr(summary.get('total_invested'))} | "
          f"Current: {_format_curr(summary.get('current_value'))} | "
          f"Overall P&L: {_format_curr(summary.get('total_unrealized_pnl'))} "
          f"({summary.get('total_pnl_pct', 0.0):.2f}%){unpriced_str}")
    print(f"Holdings Count: {summary.get('holdings_count', 0)} | "
          f"Gainers: {summary.get('gainers', 0)} | Losers: {summary.get('losers', 0)}\n")

    print("=" * 88)
    header = f"| {'#':<3} | {'Question':<40} | {'Expected (Summary)':<20} | {'Status':<14} |"
    divider = f"|{'-'*5}|{'-'*42}|{'-'*22}|{'-'*16}|"
    print(header)
    print(divider)

    results = []
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for idx, (question, metric_key) in enumerate(QUESTIONS, 1):
            expected = extract_expected_metric(metric_key, summary)
            try:
                if use_direct:
                    resp = await ask_question_direct(advisory_data, summary, question)
                else:
                    resp = await ask_question_http(client, args.url, question)
                answer = resp.get("answer", "").strip()
            except Exception as q_exc:
                answer = f"ERROR: {q_exc}"

            status = check_consistency(expected, answer)
            # Truncate for clean table display
            q_disp = question[:38] + ".." if len(question) > 40 else question
            exp_disp = expected[:18] + ".." if len(expected) > 20 else expected
            stat_disp = status[:14]

            print(f"| {idx:<3} | {q_disp:<40} | {exp_disp:<20} | {stat_disp:<14} |")
            results.append((idx, question, expected, answer, status))

    print("=" * 88)
    print("\n[Detailed Responses]")
    for idx, q, exp, ans, stat in results:
        clean_ans = ans.replace("\n", " ")
        if len(clean_ans) > 120:
            clean_ans = clean_ans[:117] + "..."
        print(f"\nQ{idx}: {q}")
        print(f"  Summary Expected : {exp}")
        print(f"  Chatbot Reply    : {clean_ans}")
        print(f"  Status           : {stat}")

    print("\n" + "=" * 88)
    print("                     EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 88)


if __name__ == "__main__":
    asyncio.run(main())
