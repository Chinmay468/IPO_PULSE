#!/usr/bin/env python3
"""
Evaluate Track Record CLI Script:
Compares score tier vs listing gain for listed IPOs and generates empirical performance metrics.
Writes the numbers used by the Scoring Methodology page, strictly enforcing the rule:
show "not enough data" for any tier with fewer than 20 IPO listings.
"""

import sys
import os
import json
import argparse
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import AsyncSessionLocal
from app.models.ipo import IPO, IPOScore, IPOStatus, IPOListing


async def evaluate_track_record(output_path: str = None) -> Dict[str, Any]:
    print("=" * 70)
    print(" IPO Pulse Track Record Evaluator (Score Tier vs Listing Gain)")
    print("=" * 70)

    tiers_data: Dict[str, Dict[str, Any]] = {
        "STRONG APPLY": {"count": 0, "gains": [], "positive_count": 0},
        "APPLY": {"count": 0, "gains": [], "positive_count": 0},
        "NEUTRAL": {"count": 0, "gains": [], "positive_count": 0},
        "AVOID": {"count": 0, "gains": [], "positive_count": 0},
    }

    total_listed = 0

    async with AsyncSessionLocal() as session:
        stmt = (
            select(IPO)
            .options(
                selectinload(IPO.score),
                selectinload(IPO.listing_info),
            )
            .where(
                (IPO.status == IPOStatus.LISTED)
                | (IPO.listing_price.isnot(None))
            )
        )
        result = await session.execute(stmt)
        ipos: List[IPO] = result.scalars().all()

        for ipo in ipos:
            base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low

            # Determine listing price & gain
            gain_pct = None
            if ipo.listing_info and ipo.listing_info.listing_gain_pct is not None:
                gain_pct = ipo.listing_info.listing_gain_pct
            elif ipo.listing_info and ipo.listing_info.listing_price and base_price and base_price > 0:
                gain_pct = round(((ipo.listing_info.listing_price - base_price) / base_price) * 100.0, 2)
            elif ipo.listing_price and base_price and base_price > 0:
                gain_pct = round(((ipo.listing_price - base_price) / base_price) * 100.0, 2)

            if gain_pct is None:
                continue

            total_listed += 1
            rec_val = "AVOID"
            if ipo.score and ipo.score.recommendation:
                rec_val = (
                    ipo.score.recommendation.value
                    if hasattr(ipo.score.recommendation, "value")
                    else str(ipo.score.recommendation)
                )

            if rec_val in tiers_data:
                tiers_data[rec_val]["count"] += 1
                tiers_data[rec_val]["gains"].append(gain_pct)
                if gain_pct > 0:
                    tiers_data[rec_val]["positive_count"] += 1

    summary_tiers: Dict[str, Any] = {}
    print(f"\nEvaluated Total Listed IPOs with price data: {total_listed}")
    print("-" * 70)
    print(f"{'Tier':<16} | {'Count':<8} | {'Avg Gain %':<14} | {'Win Rate %':<12} | {'Status'}")
    print("-" * 70)

    for tier_name in ["STRONG APPLY", "APPLY", "NEUTRAL", "AVOID"]:
        data = tiers_data[tier_name]
        count = data["count"]
        if count >= 20:
            avg_gain = round(sum(data["gains"]) / count, 2)
            win_rate = round((data["positive_count"] / count) * 100.0, 1)
            display_val = f"+{avg_gain:.1f}%" if avg_gain > 0 else f"{avg_gain:.1f}%"
            summary_tiers[tier_name] = {
                "count": count,
                "avg_gain_pct": avg_gain,
                "win_rate_pct": win_rate,
                "status": "ok",
                "display": display_val,
            }
            print(f"{tier_name:<16} | {count:<8} | {display_val:<14} | {win_rate}%{' ' * 6} | Validated (>=20)")
        else:
            summary_tiers[tier_name] = {
                "count": count,
                "avg_gain_pct": None,
                "win_rate_pct": None,
                "status": "not enough data",
                "display": "Not enough data (<20 IPOs)",
            }
            print(f"{tier_name:<16} | {count:<8} | {'N/A':<14} | {'N/A':<12} | Not enough data (<20 IPOs)")

    print("-" * 70)

    payload = {
        "threshold": 20,
        "total_evaluated_listed": total_listed,
        "tiers": summary_tiers,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Empirical listing performance computed from verified database records. Tiers with under 20 listings are withheld to prevent statistical sample bias."
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\nSaved track record metrics to: {output_path}")

    return payload


def main():
    parser = argparse.ArgumentParser(description="Evaluate IPO track record by scoring recommendation tier.")
    default_out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "track_record.json")
    parser.add_argument("--output", "-o", default=default_out, help=f"Path to write JSON output (default: {default_out})")
    args = parser.parse_args()

    asyncio.run(evaluate_track_record(args.output))


if __name__ == "__main__":
    main()
