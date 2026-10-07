import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
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


async def scheduled_prediction_generation():
    """
    Daily pre-market job (before market open IST): generates & locks direction predictions.
    """
    try:
        from app.services.prediction_service import PredictionService
        async with AsyncSessionLocal() as session:
            preds = await PredictionService.generate_daily_predictions(session)
            logger.info("Pre-market prediction generation completed: %d predictions created.", len(preds))
    except Exception as exc:
        logger.error("Error during pre-market prediction generation: %s", exc, exc_info=True)


async def scheduled_prediction_scoring():
    """
    Daily post-market job (after market close IST): scores predictions against actual close prices.
    """
    try:
        from app.services.prediction_service import PredictionService
        async with AsyncSessionLocal() as session:
            results = await PredictionService.score_daily_predictions(session)
            logger.info("Post-market prediction scoring completed: %d results scored.", len(results))
    except Exception as exc:
        logger.error("Error during post-market prediction scoring: %s", exc, exc_info=True)


async def scheduled_suggestion_evaluation():
    """
    Daily post-market job: updates open suggestions using daily candles (high/low),
    marks target or stop (whichever hit first) or expired after 45 days.
    """
    logger.info("Executing scheduled swing suggestion evaluation job...")
    try:
        from app.services.market_shares_service import evaluate_open_suggestions
        async with AsyncSessionLocal() as session:
            result = await evaluate_open_suggestions(session)
            logger.info("Scheduled swing suggestion evaluation completed: %s", result)
    except Exception as exc:
        logger.error("Error during scheduled swing suggestion evaluation: %s", exc, exc_info=True)


async def scheduled_portfolio_snapshot():
    """
    Daily post-market job (after market close IST): saves one portfolio snapshot row, using priced holdings only.
    """
    logger.info("Executing scheduled daily portfolio snapshot job...")
    try:
        from app.services.portfolio_service import take_portfolio_snapshot
        async with AsyncSessionLocal() as session:
            snapshot = await take_portfolio_snapshot(session)
            logger.info("Daily portfolio snapshot completed: %s", snapshot)
    except Exception as exc:
        logger.error("Error during daily portfolio snapshot: %s", exc, exc_info=True)


async def scheduled_mf_nav_sync():
    """
    Daily job after 10 PM IST (22:30 IST / 17:00 UTC) to fetch latest AMFI NAVs and update mutual fund schemes.
    On failure keeps last NAV and flags stale (never defaults to 0).
    """
    logger.info("Executing scheduled Mutual Fund NAV sync job...")
    try:
        from app.services.mf_nav_service import sync_all_scheme_navs
        async with AsyncSessionLocal() as session:
            result = await sync_all_scheme_navs(session, force_refresh_amfi=True)
            logger.info("Scheduled MF NAV sync completed: %s", result)
    except Exception as exc:
        logger.error("Error during scheduled MF NAV sync: %s", exc, exc_info=True)


async def scheduled_technical_diagnosis_evaluation():
    """
    Daily post-market job: updates open technical diagnoses using daily candles,
    marking whether target or stop was hit first.
    """
    logger.info("Executing scheduled technical diagnosis evaluation job...")
    try:
        from app.services.technical_analysis_service import evaluate_open_diagnoses
        async with AsyncSessionLocal() as session:
            result = await evaluate_open_diagnoses(session)
            logger.info("Scheduled technical diagnosis evaluation completed: %s", result)
    except Exception as exc:
        logger.error("Error during scheduled technical diagnosis evaluation: %s", exc, exc_info=True)


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
        scheduler.add_job(
            scheduled_prediction_generation,
            trigger=CronTrigger(hour=3, minute=30),  # 09:00 IST / 03:30 UTC
            id="daily_prediction_generation",
            name="Generate Pre-Market Direction Predictions",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_prediction_scoring,
            trigger=CronTrigger(hour=10, minute=30),  # 16:00 IST / 10:30 UTC
            id="daily_prediction_scoring",
            name="Score Post-Market Prediction Results",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_portfolio_snapshot,
            trigger=CronTrigger(hour=10, minute=35),  # 16:05 IST / 10:35 UTC
            id="daily_portfolio_snapshot",
            name="Save Daily Post-Market Portfolio Value Snapshot",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_suggestion_evaluation,
            trigger=CronTrigger(hour=10, minute=45),  # 16:15 IST / 10:45 UTC
            id="daily_suggestion_evaluation",
            name="Evaluate Open Swing Suggestions Against Daily Candles",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_technical_diagnosis_evaluation,
            trigger=CronTrigger(hour=10, minute=50),  # 16:20 IST / 10:50 UTC
            id="daily_technical_diagnosis_evaluation",
            name="Evaluate Open Technical Diagnoses Against Daily Price Movement",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_mf_nav_sync,
            trigger=CronTrigger(hour=17, minute=0),  # 22:30 IST / 17:00 UTC (after 10 PM IST)
            id="daily_mf_nav_sync",
            name="Daily Mutual Fund NAV Update after 10 PM IST",
            replace_existing=True
        )
        scheduler.start()
        logger.info(f"APScheduler started with interval of {settings.SCRAPER_INTERVAL_MINUTES} minutes.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")


