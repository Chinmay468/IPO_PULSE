import logging
from datetime import datetime, timezone
from typing import Dict, Any, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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


async def scheduled_chittorgarh_daily_sync():
    """
    Daily job for upcoming and past IPOs from Chittorgarh.
    """
    logger.info("Executing scheduled Chittorgarh daily sync (upcoming & past IPOs)...")
    try:
        from app.services.chittorgarh_scraper import sync_chittorgarh_data
        async with AsyncSessionLocal() as session:
            result = await sync_chittorgarh_data(session, only_live=False)
            logger.info("Chittorgarh daily sync completed: %s", result)
    except Exception as exc:
        logger.error("Error during scheduled Chittorgarh daily sync: %s", exc, exc_info=True)


async def scheduled_chittorgarh_live_sync():
    """
    15-minute job for live IPOs only from Chittorgarh.
    """
    logger.info("Executing scheduled Chittorgarh 15-minute live sync...")
    try:
        from app.services.chittorgarh_scraper import sync_chittorgarh_data
        async with AsyncSessionLocal() as session:
            result = await sync_chittorgarh_data(session, only_live=True)
            logger.info("Chittorgarh live sync completed: %s", result)
    except Exception as exc:
        logger.error("Error during scheduled Chittorgarh live sync: %s", exc, exc_info=True)


async def correct_ipo_statuses(session: AsyncSession) -> int:
    """
    Derives and corrects stored ipos.status based on IST dates for all active IPOs,
    and recalculates composite scores using consensus GMP and final subscription data.
    Returns the count of updated IPOs.
    """
    from app.core.ipo_timeline import derive_ipo_status
    from app.models.ipo import IPO, IPOScore, IPOGmp
    from app.services.scoring_service import ScoringService
    from app.services.consensus_gmp import ConsensusGmpService
    from sqlalchemy.orm import selectinload

    stmt = select(IPO).options(
        selectinload(IPO.score),
        selectinload(IPO.subscriptions),
        selectinload(IPO.gmp_records),
    )
    ipos = (await session.execute(stmt)).scalars().all()
    updated_count = 0
    now_utc = datetime.now(timezone.utc)

    for ipo in ipos:
        # If dates are known, dates_tba must be False
        if ipo.open_date is not None and ipo.close_date is not None and getattr(ipo, "dates_tba", False):
            ipo.dates_tba = False

        new_status = derive_ipo_status(
            ipo.open_date,
            ipo.close_date,
            ipo.listing_date,
            dates_tba=getattr(ipo, "dates_tba", False)
        )
        if ipo.status != new_status:
            ipo.status = new_status
            ipo.updated_at = now_utc

            # Recalculate score with consensus GMP
            consensus = await ConsensusGmpService.get_ipo_consensus_gmp(session, ipo.id)
            latest_gmp = None
            if consensus["status"] == "fresh" and consensus["gmp_amount"] is not None:
                latest_gmp = IPOGmp(
                    ipo_id=ipo.id,
                    gmp_amount=consensus["gmp_amount"],
                    gmp_percentage=consensus["gmp_percentage"],
                    source="consensus",
                    recorded_at=now_utc
                )
            latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
            score_data = ScoringService.calculate_score(ipo, latest_sub, latest_gmp)

            if ipo.score:
                ipo.score.composite_score = score_data["composite_score"]
                ipo.score.recommendation = score_data["recommendation"]
                ipo.score.gmp_score = score_data["gmp_score"]
                ipo.score.subscription_score = score_data["subscription_score"]
                ipo.score.valuation_score = score_data["valuation_score"]
                ipo.score.structure_score = score_data["structure_score"]
                ipo.score.rationale = score_data["rationale"]
                ipo.score.calculated_at = now_utc
            else:
                new_score = IPOScore(
                    ipo_id=ipo.id,
                    composite_score=score_data["composite_score"],
                    recommendation=score_data["recommendation"],
                    gmp_score=score_data["gmp_score"],
                    subscription_score=score_data["subscription_score"],
                    valuation_score=score_data["valuation_score"],
                    structure_score=score_data["structure_score"],
                    rationale=score_data["rationale"],
                    calculated_at=now_utc
                )
                session.add(new_score)
            updated_count += 1

    return updated_count


async def scheduled_ipo_status_correction():
    """
    Daily scheduled job that derives and corrects IPO statuses based on IST dates,
    and recalculates composite scores for newly closed/listed IPOs using final subscription data.
    """
    logger.info("Executing scheduled IPO status correction job...")
    try:
        async with AsyncSessionLocal() as session:
            updated_count = await correct_ipo_statuses(session)
            await session.commit()
            logger.info("Scheduled IPO status correction finished: %d IPO statuses updated.", updated_count)
    except Exception as exc:
        logger.error("Error during scheduled IPO status correction: %s", exc, exc_info=True)


last_unmatched_linkintime_companies: List[Dict[str, str]] = []


async def scheduled_linkintime_company_sync() -> Dict[str, Any]:
    """
    Daily background job: refreshes Link Intime companies, maps them by normalized name
    to database IPOs, updates registrar_code and registrar_name, and reports unmatched companies.
    """
    global last_unmatched_linkintime_companies
    logger.info("Executing daily Link Intime company mapping job...")
    try:
        from app.services.registrar_proxy import RegistrarProxyService
        from app.core.registrars import CanonicalRegistrar, DEFAULT_REGISTRAR_URLS
        from app.services.chittorgarh_scraper import normalize_company_name
        from app.models.ipo import IPO

        companies = await RegistrarProxyService.get_linkintime_companies()
        if not companies:
            logger.warning("No companies returned from Link Intime; skipping mapping.")
            return {"total_companies": 0, "matched": 0, "unmatched": []}

        async with AsyncSessionLocal() as session:
            ipos = (await session.execute(select(IPO))).scalars().all()
            ipo_by_norm = {normalize_company_name(ipo.company_name): ipo for ipo in ipos if ipo.company_name}

            matched_count = 0
            unmatched = []

            for comp in companies:
                cname = comp.company_name
                norm = normalize_company_name(cname)
                matched_ipo = ipo_by_norm.get(norm)
                if matched_ipo:
                    matched_ipo.registrar_name = CanonicalRegistrar.LINKINTIME
                    matched_ipo.registrar_code = comp.company_id
                    if not matched_ipo.registrar_allotment_url:
                        matched_ipo.registrar_allotment_url = DEFAULT_REGISTRAR_URLS[CanonicalRegistrar.LINKINTIME]
                    matched_count += 1
                else:
                    unmatched.append({"company_id": comp.company_id, "company_name": comp.company_name})

            await session.commit()
            last_unmatched_linkintime_companies = unmatched

            if unmatched:
                logger.warning(f"Unmatched Link Intime companies ({len(unmatched)}): {unmatched}")
            else:
                logger.info(f"All {matched_count} Link Intime companies mapped successfully.")

            return {
                "total_companies": len(companies),
                "matched": matched_count,
                "unmatched": unmatched
            }
    except Exception as exc:
        logger.error(f"Error during daily Link Intime company mapping: {exc}", exc_info=True)
        return {"error": str(exc)}


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
            scheduled_chittorgarh_daily_sync,
            trigger=CronTrigger(hour=0, minute=30),  # 06:00 IST / 00:30 UTC
            id="chittorgarh_daily_sync",
            name="Daily Chittorgarh Scrape for Upcoming and Past IPOs",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_chittorgarh_live_sync,
            trigger=IntervalTrigger(minutes=15),
            id="chittorgarh_live_sync",
            name="15-Minute Chittorgarh Scrape for Live IPOs",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_ipo_status_correction,
            trigger=CronTrigger(hour=11, minute=35),  # 17:05 IST / 11:35 UTC (after 5 PM IST close)
            id="daily_ipo_status_correction",
            name="Daily IPO Status Correction and Score Recalculation (17:05 IST)",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_ipo_status_correction,
            trigger=CronTrigger(hour=18, minute=35),  # 00:05 IST / 18:35 UTC (midnight rollover)
            id="daily_midnight_ipo_status_correction",
            name="Daily Midnight IPO Status Correction (00:05 IST)",
            replace_existing=True
        )
        scheduler.add_job(
            scheduled_linkintime_company_sync,
            trigger=CronTrigger(hour=1, minute=0),  # 06:30 IST / 01:00 UTC (daily morning)
            id="daily_linkintime_company_sync",
            name="Daily Link Intime Company Mapping to IPOs",
            replace_existing=True
        )
        scheduler.start()
        logger.info(f"APScheduler started with interval of {settings.SCRAPER_INTERVAL_MINUTES} minutes.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
