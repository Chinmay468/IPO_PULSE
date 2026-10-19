"""
Fix stale allotment-discovered IPOs that were erroneously marked as UPCOMING.
Updates their life-cycle status to LISTED/CLOSED and populates actual dates.
"""
import asyncio
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.ipo import IPO, IPOStatus
from app.services.chittorgarh_scraper import ChittorgarhClient, parse_ipo_detail


async def fix_stale_allotment_ipos():
    client = ChittorgarhClient(delay_seconds=0.2)
    async with AsyncSessionLocal() as session:
        stmt = select(IPO).where(
            IPO.source == "chittorgarh_allotment",
            IPO.status == IPOStatus.UPCOMING
        )
        res = await session.execute(stmt)
        stale_ipos = res.scalars().all()
        print(f"Found {len(stale_ipos)} stale allotment IPOs currently marked UPCOMING.")

        fixed_with_detail = 0
        fixed_fallback = 0

        # Prioritize top ones first
        for ipo in stale_ipos:
            updated = False
            if ipo.source_id:
                try:
                    slug = ipo.company_name.lower().replace(" ", "-").replace(".", "").replace("&", "and")
                    url = f"https://www.chittorgarh.com/ipo/{slug}-ipo/{ipo.source_id}/"
                    html = await client.fetch(url)
                    detail = parse_ipo_detail(html, ipo.source_id, url)
                    if detail and (detail.get("open_date") or detail.get("close_date") or detail.get("listing_date")):
                        ipo.open_date = detail.get("open_date") or ipo.open_date
                        ipo.close_date = detail.get("close_date") or ipo.close_date
                        ipo.listing_date = detail.get("listing_date") or ipo.listing_date
                        ipo.price_band_low = detail.get("price_band_low") or ipo.price_band_low
                        ipo.price_band_high = detail.get("price_band_high") or ipo.price_band_high
                        ipo.issue_price = detail.get("issue_price") or ipo.issue_price
                        ipo.status = detail.get("status") or IPOStatus.LISTED
                        ipo.dates_tba = False
                        fixed_with_detail += 1
                        updated = True
                except Exception:
                    pass

            if not updated:
                ipo.status = IPOStatus.LISTED
                ipo.dates_tba = False
                fixed_fallback += 1

        await session.commit()
        print(f"Successfully corrected {len(stale_ipos)} IPOs: {fixed_with_detail} with full prospectus dates, {fixed_fallback} marked LISTED.")


if __name__ == "__main__":
    asyncio.run(fix_stale_allotment_ipos())
