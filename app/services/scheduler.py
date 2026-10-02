import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.scraper_service import ScraperService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_market_sync():
    """
    Scheduled job that runs periodically to fetch GMP, subscription data, and update scores.
    """
    logger.info("Executing scheduled market scraper job...")
    try:
        async with AsyncSessionLocal() as session:
            result = await ScraperService.sync_market_data(session)
            logger.info(f"Scheduled market sync completed: {result}")

            # Send real-time Telegram alerts for top-tier IPOs
            from app.services.telegram_service import TelegramService
            if TelegramService.is_configured():
                alert_res = await TelegramService.send_best_ipo_alerts(session)
                logger.info(f"Telegram alerts processed: {alert_res}")
    except Exception as exc:
        logger.error(f"Error during scheduled market sync: {exc}", exc_info=True)


async def scheduled_portfolio_sync():
    """
    Scheduled background job to automatically pull latest holdings from Angel One SmartAPI.
    """
    try:
        from app.services.angelone_sync_service import _is_configured, sync_angelone_to_portfolio
        if not _is_configured():
            return
        async with AsyncSessionLocal() as session:
            result = await sync_angelone_to_portfolio(session)
            logger.info(f"Scheduled Angel One portfolio sync completed: {result}")
    except Exception as exc:
        logger.debug(f"Angel One background sync skipped/notice: {exc}")


def start_scheduler():
    if not settings.SCRAPER_ENABLED:
        logger.info("Background market scraper is disabled in settings.")
        return

    if not scheduler.running:
        scheduler.add_job(
            scheduled_market_sync,
            trigger=IntervalTrigger(minutes=settings.SCRAPER_INTERVAL_MINUTES),
            id="market_scraper_sync",
            name="Scrape IPO Market Feeds and Recalculate Scores",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_portfolio_sync,
            trigger=IntervalTrigger(minutes=15),
            id="portfolio_angelone_sync",
            name="Sync Portfolio Holdings from Angel One SmartAPI",
            replace_existing=True
        )
        scheduler.start()
        logger.info(f"APScheduler started with interval of {settings.SCRAPER_INTERVAL_MINUTES} minutes.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")

