#!/usr/bin/env python3
"""
Price History Historical Backfill CLI Runner.
Fetches up to 5 years of daily candles from yfinance for every portfolio holding
and default watchlist symbol (not only from the purchase date).
Handles listings with short history cleanly, retries with exponential backoff,
sleeps between symbols to avoid rate limits, and validates every candle.

Usage:
  python scripts/backfill_prices.py
  python scripts/backfill_prices.py --years 5 --sleep 0.5
  python scripts/backfill_prices.py --symbols RELIANCE,TCS,INFY
"""

import os
import sys
import argparse
import asyncio
import logging

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import AsyncSessionLocal
from app.services.price_history_service import (
    backfill_symbol,
    get_all_tracked_symbols,
    clean_symbol
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_prices")


async def run_backfill(symbols: list[str] = None, years: int = 5, sleep_sec: float = 0.5):
    logger.info("Initializing Price History Backfill (Years=%d, Sleep=%.2fs)...", years, sleep_sec)

    async with AsyncSessionLocal() as session:
        if symbols:
            target_symbols = [(clean_symbol(s), "NSE") for s in symbols]
        else:
            target_symbols = await get_all_tracked_symbols(session)

        logger.info("Targeting %d symbols for backfill: %s", len(target_symbols), [s[0] for s in target_symbols])
        print(f"\n{'='*75}")
        print(f"STARTING PRICE HISTORY BACKFILL: {len(target_symbols)} SYMBOLS (LOOKBACK={years}y)")
        print(f"{'='*75}\n")

        total_upserted = 0
        total_rejected = 0
        total_issues = 0
        summary_rows = []

        for idx, (sym, ex) in enumerate(target_symbols, start=1):
            sys.stdout.write(f"[{idx}/{len(target_symbols)}] Backfilling {sym} ({ex})... ")
            sys.stdout.flush()

            try:
                res = await backfill_symbol(session, sym, exchange=ex, years=years, sleep_sec=sleep_sec)
                upserted = res.get("upserted", 0)
                rejected = res.get("rejected", 0)
                issues = res.get("issues", 0)

                total_upserted += upserted
                total_rejected += rejected
                total_issues += issues

                sys.stdout.write(f"Done ({upserted} rows, {rejected} rejected, {issues} flagged)\n")
                summary_rows.append({
                    "symbol": sym,
                    "exchange": ex,
                    "rows": upserted,
                    "rejected": rejected,
                    "issues": issues,
                    "status": "OK"
                })
            except Exception as exc:
                sys.stdout.write(f"FAILED ({exc})\n")
                summary_rows.append({
                    "symbol": sym,
                    "exchange": ex,
                    "rows": 0,
                    "rejected": 0,
                    "issues": 0,
                    "status": f"ERROR: {exc}"
                })

        print(f"\n{'='*75}")
        print("BACKFILL SUMMARY REPORT")
        print(f"{'='*75}")
        print(f"{'Symbol':<15} {'Exchange':<10} {'Rows Stored':<15} {'Rejected':<12} {'Issues/Flags':<12} {'Status'}")
        print("-" * 75)
        for r in summary_rows:
            print(f"{r['symbol']:<15} {r['exchange']:<10} {r['rows']:<15} {r['rejected']:<12} {r['issues']:<12} {r['status']}")
        print("-" * 75)
        print(f"TOTALS: {len(target_symbols)} symbols | {total_upserted} rows stored | {total_rejected} rejected | {total_issues} issues/flags")
        print(f"{'='*75}\n")


def main():
    parser = argparse.ArgumentParser(description="Backfill historical daily candles from yfinance into price_history")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated symbols (e.g. RELIANCE,TCS)")
    parser.add_argument("--years", type=int, default=5, help="Years of history to backfill (default: 5)")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between symbols (default: 0.5)")

    args = parser.parse_args()
    sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None

    asyncio.run(run_backfill(symbols=sym_list, years=args.years, sleep_sec=args.sleep))


if __name__ == "__main__":
    main()
