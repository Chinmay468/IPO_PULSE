from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import require_auth
from app.services.scraper_service import ScraperService
from app.services.scheduler import scheduler
from app.config import settings

router = APIRouter(prefix="/scraper", tags=["Market Data Scraper"], dependencies=[Depends(require_auth)])


@router.post("/sync", summary="Manually trigger market data sync and score recalculation")
async def trigger_market_sync(db: AsyncSession = Depends(get_db)):
    """
    Triggers an immediate background scrape of live GMP and subscription feeds,
    updates IPO records, and recomputes composite scores.
    """
    result = await ScraperService.sync_market_data(db)
    return result


@router.post("/seed", summary="Seed initial IPO master data with historical subscriptions & GMP")
async def seed_market_data(db: AsyncSession = Depends(get_db)):
    """
    Populates default market data for live, upcoming, and closed IPOs with
    verified benchmark metrics and recommendations.
    """
    count = await ScraperService.seed_market_data(db)
    return {"message": f"Successfully seeded {count} IPO records with subscriptions, GMP, and scores."}


@router.get("/status", summary="Check scraper status and scheduler health")
async def get_scraper_status():
    """
    Returns the operational state of the background market scraper and next scheduled run.
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

    return {
        "scraper_enabled": settings.SCRAPER_ENABLED,
        "scheduler_running": is_running,
        "interval_minutes": settings.SCRAPER_INTERVAL_MINUTES,
        "jobs": jobs
    }
