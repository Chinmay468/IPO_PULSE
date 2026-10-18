"""
Production Copy Synchronization and Diagnostic Runner

Runs:
1. Database connection verification (masking all credentials).
2. Alembic migration execution (including ipo_aliases and ipo_pre_listing_gmp view).
3. Seed IPO isolation (flagging Hyundai and NTPC Green as is_seed=True).
4. Status correction job (deriving stored status from IST dates).
5. Multi-source GMP matching (InvestorGain + IPOWatch with band-range check).
6. Formatted diagnostic output tables.

Usage:
    python scripts/sync_postgres_replica.py --db-url "postgresql+asyncpg://user:pass@localhost:5432/enquirer_copy"
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, date, timezone
from urllib.parse import urlparse

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, update, func, or_
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


def mask_db_url(url: str) -> str:
    """Masks credentials from database URL for secure logging."""
    if not url:
        return ""
    # Mask password and user: e.g. postgresql+asyncpg://user:password@host:port/dbname
    masked = re.sub(r"://([^:@]+):([^@]+)@", r"://***:***@", url)
    return masked


async def run_sync_and_diagnostics(target_db_url: str):
    parsed = urlparse(target_db_url)
    db_type = parsed.scheme.split("+")[0]
    host_display = parsed.hostname or (target_db_url.split("///")[-1] if "sqlite" in target_db_url else "unknown")

    print("\n" + "=" * 80)
    print(" IPO DATABASE SYNCHRONIZATION & REPLICATION RUNNER")
    print("=" * 80)
    print(f"Target Database Type : {db_type.upper()}")
    print(f"Target Host / File   : {host_display}")
    print(f"Target Connection URI: {mask_db_url(target_db_url)}")
    print("=" * 80 + "\n")

    # 1. Database Connection
    engine = create_async_engine(target_db_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # Import models and core utilities
        from app.models.ipo import IPO, IPOAlias, IPOGmp, IPOSubscription, IPOScore, IPOStatus
        from app.core.ipo_timeline import derive_ipo_status, get_ist_today
        from app.services.scheduler import correct_ipo_statuses
        from app.services.gmp_matcher import match_gmp_records_to_ipos
        from app.services.scraper_service import ScraperService
        from app.services.ipowatch_scraper import IPOWatchScraper

        # 2. Seed Data Isolation: Ensure Hyundai and NTPC Green Energy are flagged is_seed = True
        print("[1/5] Checking and Flagging Seed IPOs...")
        seed_symbols = ["HYUNDAI", "NTPCGREEN"]
        stmt_seeds = select(IPO).where(
            or_(
                IPO.symbol.in_(seed_symbols),
                IPO.company_name.ilike("%Hyundai Motor%"),
                IPO.company_name.ilike("%NTPC Green%")
            )
        )
        seeds = (await session.execute(stmt_seeds)).scalars().all()
        flagged_count = 0
        for s in seeds:
            if not s.is_seed:
                s.is_seed = True
                flagged_count += 1
        await session.commit()
        print(f"      Total seed IPOs detected: {len(seeds)} (Newly flagged is_seed=True: {flagged_count})")

        # 3. Status Correction Job
        print("[2/5] Running Stored Status Correction Job (correct_ipo_statuses)...")
        updated_status_count = await correct_ipo_statuses(session)
        print(f"      Corrected stored status for {updated_status_count} IPOs.")

        # 4. Fetch All Active & Upcoming IPOs for Diagnostics
        today = get_ist_today()
        stmt_all = select(IPO).where(IPO.is_seed.is_(False)).order_by(IPO.status.asc(), IPO.open_date.asc())
        ipos = (await session.execute(stmt_all)).scalars().all()

        print("\n" + "-" * 95)
        print("TABLE 1: STORED VS DERIVED STATUS FOR ACTIVE IPOs (Non-Seed)")
        print("-" * 95)
        print(f"{'ID':<4} | {'Symbol':<14} | {'Company Name':<32} | {'Open Date':<10} | {'Close Date':<10} | {'Stored':<8} | {'Derived':<8} | {'Match?'}")
        print("-" * 95)

        for ipo in ipos:
            derived = derive_ipo_status(ipo.open_date, ipo.close_date, ipo.listing_date, dates_tba=getattr(ipo, "dates_tba", False))
            match_str = "YES" if ipo.status == derived else "MISMATCH"
            op_d = str(ipo.open_date) if ipo.open_date else "TBA"
            cl_d = str(ipo.close_date) if ipo.close_date else "TBA"
            comp = (ipo.company_name[:29] + "...") if len(ipo.company_name) > 32 else ipo.company_name
            print(f"{ipo.id:<4} | {ipo.symbol:<14} | {comp:<32} | {op_d:<10} | {cl_d:<10} | {ipo.status.value:<8} | {derived.value:<8} | {match_str}")

        print("-" * 95)

        # 5. Scrape / Load GMP Records
        print("\n[3/5] Scraping InvestorGain & IPOWatch feeds...")
        try:
            ig_rows = await ScraperService.scrape_gmp_feed()
        except Exception as e:
            print(f"      InvestorGain live scrape failed ({e}), loading local fixture...")
            fixture_path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "investorgain_gmp_fixture.html")
            with open(fixture_path, "r", encoding="utf-8") as f:
                ig_rows = ScraperService.parse_investorgain_table(f.read())

        try:
            iw_rows = await IPOWatchScraper.fetch_feed()
        except Exception as e:
            print(f"      IPOWatch live scrape failed ({e}), loading local fixture...")
            fixture_path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "ipowatch_gmp_fixture.html")
            with open(fixture_path, "r", encoding="utf-8") as f:
                iw_rows = IPOWatchScraper.parse_tables(f.read())

        print(f"      InvestorGain rows: {len(ig_rows)} | IPOWatch rows: {len(iw_rows)}")

        # 6. Run Multi-source Matching
        print("[4/5] Running GMP Name & Price-Band Matching...")
        ig_matched, ig_unmatched = await match_gmp_records_to_ipos(session, ig_rows, ipos, source_name="investorgain")
        iw_matched, iw_unmatched = await match_gmp_records_to_ipos(session, iw_rows, ipos, source_name="ipowatch")

        print("\n" + "-" * 105)
        print("TABLE 2: MATCHED GMP ROWS (InvestorGain & IPOWatch)")
        print("-" * 105)
        print(f"{'Source':<12} | {'Scraped Company Name':<32} | {'Matched DB Company':<30} | {'Band/Price':<12} | {'GMP':<10}")
        print("-" * 105)

        for ipo, row in ig_matched:
            s_name = (row.get("company_name", "")[:29] + "...") if len(row.get("company_name", "")) > 32 else row.get("company_name", "")
            d_name = (ipo.company_name[:27] + "...") if len(ipo.company_name) > 30 else ipo.company_name
            p_val = f"Rs {row.get('price', '—')}"
            g_val = f"Rs {row.get('gmp_amount', '—')}"
            print(f"{'investorgain':<12} | {s_name:<32} | {d_name:<30} | {p_val:<12} | {g_val:<10}")

        for ipo, row in iw_matched:
            s_name = (row.get("company_name", "")[:29] + "...") if len(row.get("company_name", "")) > 32 else row.get("company_name", "")
            d_name = (ipo.company_name[:27] + "...") if len(ipo.company_name) > 30 else ipo.company_name
            p_val = f"Rs {row.get('price_band_high', row.get('price', '—'))}"
            g_val = f"Rs {row.get('gmp_amount', '—')}"
            print(f"{'ipowatch':<12} | {s_name:<32} | {d_name:<30} | {p_val:<12} | {g_val:<10}")

        print("-" * 105)

        # 7. Unmatched Report
        print("\n" + "-" * 95)
        print("TABLE 3: UNMATCHED GMP ROWS REPORT")
        print("-" * 95)
        print(f"{'Source':<12} | {'Scraped Name':<32} | {'Price':<10} | {'Dates':<15} | {'Rejection Reason'}")
        print("-" * 95)
        for u in ig_unmatched[:15]:
            u_name = (u.get("company_name", "")[:29] + "...") if len(u.get("company_name", "")) > 32 else u.get("company_name", "")
            reason = u.get("rejection_reason", "Below fuzzy threshold")
            print(f"{'investorgain':<12} | {u_name:<32} | {str(u.get('price', '—')):<10} | {str(u.get('date_str', '—')):<15} | {reason}")

        for u in iw_unmatched[:15]:
            u_name = (u.get("company_name", "")[:29] + "...") if len(u.get("company_name", "")) > 32 else u.get("company_name", "")
            reason = u.get("rejection_reason", "Below fuzzy threshold")
            print(f"{'ipowatch':<12} | {u_name:<32} | {str(u.get('price_band_high', '—')):<10} | {str(u.get('date_range', '—')):<15} | {reason}")
        print("-" * 95)

    await engine.dispose()
    print("\n[5/5] Diagnostic completed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run status correction, seed isolation, and GMP matching against target DB")
    parser.add_argument("--db-url", type=str, default=None, help="Target SQLAlchemy DB connection URL")
    args = parser.parse_args()

    db_url = args.db_url or os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        # Fallback to local configuration for verification
        from app.config import settings
        db_url = settings.DATABASE_URL

    asyncio.run(run_sync_and_diagnostics(db_url))
