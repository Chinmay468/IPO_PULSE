import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import require_auth
from app.models.ipo import IPO
from app.services.scraper_service import ScraperService
from app.services.scheduler import scheduler
from app.config import settings

router = APIRouter(prefix="/scraper", tags=["Market Data Scraper"])


@router.post("/sync", summary="Manually trigger market data sync and score recalculation")
async def trigger_market_sync(
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(require_auth)
):
    """
    Triggers an immediate background scrape of live GMP and subscription feeds,
    updates IPO records, and recomputes composite scores.
    """
    result = await ScraperService.sync_market_data(db)
    return result


@router.post("/sync-details", summary="Manually trigger Chittorgarh IPO details sync")
async def trigger_chittorgarh_sync(
    only_live: bool = Query(default=False, description="Sync only live IPOs"),
    max_pages: Optional[int] = Query(default=None, description="Max detail pages to scrape"),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(require_auth)
):
    """
    Triggers manual sync of Chittorgarh IPO listings, details, documents, anchor allocations,
    and reviews summaries with compliance, rate limiting, and caching.
    """
    from app.services.chittorgarh_scraper import sync_chittorgarh_data
    result = await sync_chittorgarh_data(db, only_live=only_live, max_detail_pages=max_pages)
    return result


@router.post("/seed", summary="Seed initial IPO master data with historical subscriptions & GMP")
async def seed_market_data(
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(require_auth)
):
    """
    Populates default market data for live, upcoming, and closed IPOs with
    verified benchmark metrics and recommendations.
    Refuses to execute unless ALLOW_SEED=1 environment variable is set.
    """
    if os.getenv("ALLOW_SEED") != "1":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeding market data is disabled in production unless ALLOW_SEED=1 is explicitly set."
        )
    count = await ScraperService.seed_market_data(db)
    return {"message": f"Successfully seeded {count} IPO records with subscriptions, GMP, and scores."}


@router.get("/status", summary="Check scraper status, scheduler health, and sync freshness")
async def get_scraper_status(db: AsyncSession = Depends(get_db)):
    """
    Returns the operational state of the background market scraper, next scheduled run,
    and last discovery sync timestamp with 24-hour freshness audit.
    """
    is_running = scheduler.running
    jobs = []
    if is_running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
            })

    # Check last discovery sync timestamp from DB
    stmt = select(func.max(IPO.fetched_at)).where(IPO.source == "chittorgarh")
    last_fetched = (await db.execute(stmt)).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    is_stale = False
    age_seconds = None
    if last_fetched:
        if last_fetched.tzinfo is None:
            last_fetched = last_fetched.replace(tzinfo=timezone.utc)
        age_seconds = (now - last_fetched).total_seconds()
        is_stale = age_seconds > (24 * 3600)
    else:
        is_stale = True

    return {
        "scraper_enabled": settings.SCRAPER_ENABLED,
        "scheduler_running": is_running,
        "interval_minutes": settings.SCRAPER_INTERVAL_MINUTES,
        "jobs": jobs,
        "last_full_sync": last_fetched.isoformat() if last_fetched else None,
        "last_sync_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "is_discovery_stale": is_stale,
        "stale_warning": "Discovery sync has not completed within 24 hours. Primary listings may be stale." if is_stale else None,
        "gmp_quality": ScraperService.get_gmp_quality_status()
    }
