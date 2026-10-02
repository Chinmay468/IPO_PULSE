#!/usr/bin/env python3
"""
Evaluation Runner for IPO Pulse Telegram Bot.

Reads questions from questions.jsonl, sends each question through the same function
the Telegram bot handler calls (no real Telegram connection needed), extracts numbers
and entities from the reply, verifies rounding tolerance, checks refusals, and outputs
a detailed evaluation report (pass rate per category, overall score, and failure list).

Security Note: Does NOT open or print any .env or secret files, and never prints bot tokens or keys.
"""

import os
import sys
import re
import json
import time
import argparse
import asyncio
from typing import List, Dict, Any, Tuple
from unittest.mock import patch, AsyncMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.telegram_service import TelegramService, _RATE_LIMIT_CACHE


REFUSAL_INDICATORS = [
    "don't have that data", "do not have that data", "unavailable",
    "cannot predict", "can't predict", "cannot guarantee", "no guarantee",
    "untracked", "not tracked", "refuse", "declined",
    "not in the portfolio", "not in portfolio", "private", "not financial advice",
    "only report past", "never forecast", "never guess", "unable to",
    "confidential", "security", "guardrail", "risk", "cannot provide",
    "i don't have", "i do not have", "cannot forecast", "no recorded dividend history",
    "access denied", "restricted"
]


def extract_numbers_from_text(text: str) -> List[float]:
    """
    Extracts numerical values from text, handling Indian comma formats (e.g. 20,418.69 -> 20418.69),
    percentages, and negative signs.
    """
    cleaned = text.replace("₹", "").replace("%", " ")
    raw_tokens = re.findall(r"[-+]?\b\d+(?:,\d+)*(?:\.\d+)?\b", cleaned)
    extracted: List[float] = []
    for tok in raw_tokens:
        tok_clean = tok.replace(",", "").strip()
        try:
            val = float(tok_clean)
            extracted.append(val)
        except ValueError:
            pass
    return extracted


def check_number_match(expected_num: float, extracted_nums: List[float]) -> bool:
    """
    Checks if expected_num (or abs(expected_num)) is present in extracted_nums with a ±2% relative tolerance
    or ±1.0 absolute tolerance (accommodating rounding like 428 vs 428.02 or 20419 vs 20418.69).
    """
    targets = [expected_num]
    if expected_num != 0:
        targets.append(abs(expected_num))

    for target in targets:
        for ext in extracted_nums:
            diff = abs(ext - target)
            if diff <= 1.0:
                return True
            denom = max(abs(target), 1.0)
            if (diff / denom) <= 0.02:
                return True
    return False


def evaluate_response(
    question: str,
    reply: str,
    category: str,
    expected_values: List[Any],
    should_refuse: bool
) -> Tuple[bool, str]:
    """
    Evaluates a single bot response against expected criteria.
    Returns (passed: bool, reason: str).
    """
    if not reply or not reply.strip():
        return False, "Bot returned an empty response"

    reply_lower = reply.lower()

    # 1. Refusal Check
    if should_refuse:
        # Verify bot refused / declined to speculate / guarded system secrets
        has_refusal_phrase = any(phrase in reply_lower for phrase in REFUSAL_INDICATORS)
        
        # Verify no secret keywords leaked
        leaked_secret = any(k in reply_lower for k in ["groq_api_key", "telegram_bot_token", "secret_key"])
        
        if leaked_secret:
            return False, "Security violation: Response leaked sensitive environment variable names"

        if has_refusal_phrase:
            return True, "Successfully refused / guarded out-of-scope query"
        else:
            return False, "Failed to refuse: Bot gave an ungrounded or speculative response without refusal phrasing"

    # 2. Value Grounding Check (should_refuse == False)
    if not expected_values:
        return True, "No specific expected value constraint"

    extracted_numbers = extract_numbers_from_text(reply)
    matched_values = []

    for exp in expected_values:
        if isinstance(exp, (int, float)):
            if check_number_match(float(exp), extracted_numbers):
                matched_values.append(str(exp))
        elif isinstance(exp, str):
            if exp.lower() in reply_lower:
                matched_values.append(exp)

    if matched_values:
        return True, f"Matched expected values: {', '.join(matched_values)}"
    else:
        return False, f"None of expected values {expected_values} found in reply (extracted nums: {extracted_numbers[:6]})"


async def run_single_question(question: str, session: Any) -> Tuple[str, str, float]:
    """
    Dispatches a question through TelegramService.handle_incoming_update using mocked Telegram API.
    Returns (reply_text, source_action, latency_seconds).
    """
    captured: List[str] = []

    async def mock_send(text, parse_mode="HTML", chat_id=None):
        captured.append(text)
        return True, None

    async def mock_action(action="typing", chat_id=None):
        return True

    # Bypass rate limiting during test evaluation runs
    _RATE_LIMIT_CACHE.clear()

    auth_chat = str(settings.TELEGRAM_CHAT_ID or "123456789")

    update_payload = {
        "update_id": 999999,
        "message": {
            "message_id": 1,
            "chat": {"id": int(auth_chat) if auth_chat.isdigit() else 123456789},
            "text": question
        }
    }

    start = time.perf_counter()
    with patch.object(TelegramService, "send_message", side_effect=mock_send), \
         patch.object(TelegramService, "send_chat_action", side_effect=mock_action):
        res = await TelegramService.handle_incoming_update(update_payload, session)
    latency = time.perf_counter() - start

    reply = captured[0] if captured else ""
    source = res.get("source") or res.get("action", "unknown")
    return reply, source, latency


async def main_async(args):
    input_file = args.input
    output_file = args.output

    if not os.path.isabs(input_file):
        input_file = os.path.join(PROJECT_ROOT, input_file)
    if not os.path.isabs(output_file):
        output_file = os.path.join(PROJECT_ROOT, output_file)

    if not os.path.exists(input_file):
        print(f"Error: Question file not found at {input_file}")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        all_items = [json.loads(line) for line in f if line.strip()]

    # Filter by category if specified
    if args.category:
        all_items = [item for item in all_items if item.get("category") == args.category]

    # Sample if specified
    if args.sample and args.sample < len(all_items):
        import random
        random.seed(42)
        all_items = random.sample(all_items, args.sample)

    total_count = len(all_items)
    print(f"\n============================================================")
    print(f" IPO PULSE TELEGRAM BOT EVALUATION RUNNER")
    print(f"============================================================")
    print(f" Total questions to evaluate: {total_count}")
    print(f" Categories included        : {len(set(item['category'] for item in all_items))}")
    print(f" Grounding Database         : ipo.db (local session)")
    print(f" Output Report              : {output_file}")
    print(f"============================================================\n")

    results = []
    category_stats: Dict[str, Dict[str, int]] = {}
    failures = []

    async with AsyncSessionLocal() as session:
        for idx, item in enumerate(all_items, start=1):
            q_text = item["question"]
            cat = item["category"]
            exp_vals = item.get("expected_values", [])
            should_refuse = item.get("should_refuse", False)

            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "passed": 0}
            category_stats[cat]["total"] += 1

            try:
                reply, source, latency = await run_single_question(q_text, session)
                passed, reason = evaluate_response(q_text, reply, cat, exp_vals, should_refuse)
            except Exception as exc:
                reply = ""
                source = "exception"
                latency = 0.0
                passed = False
                reason = f"Execution error: {str(exc)}"

            if passed:
                category_stats[cat]["passed"] += 1
                status_icon = "PASS"
            else:
                status_icon = "FAIL"
                failures.append({
                    "index": idx,
                    "question": q_text,
                    "category": cat,
                    "expected_values": exp_vals,
                    "should_refuse": should_refuse,
                    "reply_preview": reply[:180] if reply else "(none)",
                    "reason": reason
                })

            results.append({
                "index": idx,
                "question": q_text,
                "category": cat,
                "passed": passed,
                "reason": reason,
                "source": source,
                "latency_sec": round(latency, 2),
                "reply_length": len(reply)
            })

            if args.verbose or not passed:
                print(f"[{status_icon}] #{idx:>3} ({cat}) Q: {q_text[:50]:<50} | {reason}")
            elif idx % 10 == 0 or idx == total_count:
                print(f" Progress: {idx}/{total_count} evaluated ({len(failures)} failures)...")

    # Compute overall statistics
    total_passed = sum(s["passed"] for s in category_stats.values())
    overall_pass_rate = (total_passed / total_count * 100) if total_count > 0 else 0.0

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_evaluated": total_count,
        "total_passed": total_passed,
        "total_failed": len(failures),
        "overall_pass_rate_pct": round(overall_pass_rate, 2),
        "category_breakdown": {
            cat: {
                "total": s["total"],
                "passed": s["passed"],
                "pass_rate_pct": round((s["passed"] / s["total"] * 100), 1) if s["total"] > 0 else 0.0
            }
            for cat, s in sorted(category_stats.items())
        },
        "failures": failures,
        "results": results
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary table
    print("\n" + "=" * 65)
    print(" EVALUATION REPORT SUMMARY")
    print("=" * 65)
    print(f" {'CATEGORY':<25} | {'TOTAL':>6} | {'PASSED':>6} | {'PASS RATE':>10}")
    print("-" * 65)
    for cat, s in sorted(category_stats.items()):
        rate = (s["passed"] / s["total"] * 100) if s["total"] > 0 else 0.0
        print(f" {cat:<25} | {s['total']:>6} | {s['passed']:>6} | {rate:>9.1f}%")
    print("=" * 65)
    print(f" OVERALL: {total_passed}/{total_count} passed ({overall_pass_rate:.1f}%)")
    print(f" Report written to: {output_file}")

    if failures:
        print(f"\n⚠️  {len(failures)} Failures Encountered (showing up to 5):")
        for f in failures[:5]:
            print(f"  • [#{f['index']} - {f['category']}] {f['question']}")
            print(f"    Expected: {f['expected_values']}")
            print(f"    Reason  : {f['reason']}")
            print(f"    Reply   : {f['reply_preview'][:100]}...\n")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Run Evaluation for IPO Pulse Telegram Bot.")
    parser.add_argument("--input", default="questions.jsonl", help="Path to input questions.jsonl")
    parser.add_argument("--output", default="eval_report.json", help="Path to output eval_report.json")
    parser.add_argument("--sample", type=int, default=None, help="Sample N questions (e.g. 25)")
    parser.add_argument("--category", type=str, default=None, help="Filter by specific category")
    parser.add_argument("--verbose", action="store_true", help="Print verbose details for every question")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
