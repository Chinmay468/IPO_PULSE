import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ipo import IPOGmp

logger = logging.getLogger(__name__)


class ConsensusGmpService:
    FRESH_WINDOW_HOURS = 12
    STALE_LIMIT_HOURS = 24

    @classmethod
    def calculate_consensus_from_readings(
        cls,
        readings: List[IPOGmp],
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Calculates consensus GMP from a list of IPOGmp objects:
        - Filters readings recorded in the last 12 hours (fresh).
        - Keeps latest reading per distinct source.
        - Readings > 24 hours count as missing.
        - Calculates median across fresh sources.
        - Evaluates disagreement: >30% relative or >Rs 25 when median < Rs 80.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # 1. Filter out readings older than STALE_LIMIT_HOURS (24h)
        stale_cutoff = now - timedelta(hours=cls.STALE_LIMIT_HOURS)
        fresh_cutoff = now - timedelta(hours=cls.FRESH_WINDOW_HOURS)

        valid_readings = [
            r for r in readings
            if r.recorded_at and (
                r.recorded_at.tzinfo is not None and r.recorded_at >= stale_cutoff or
                r.recorded_at.tzinfo is None and r.recorded_at.replace(tzinfo=timezone.utc) >= stale_cutoff
            )
        ]

        # Compute last known reading if any readings exist
        last_known = None
        if readings:
            def _get_dt(r):
                if not r.recorded_at:
                    return datetime.min.replace(tzinfo=timezone.utc)
                return r.recorded_at if r.recorded_at.tzinfo else r.recorded_at.replace(tzinfo=timezone.utc)

            sorted_all = sorted(readings, key=_get_dt, reverse=True)
            if sorted_all and sorted_all[0].recorded_at:
                lr = sorted_all[0]
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                lr_dt = lr.recorded_at if lr.recorded_at.tzinfo else lr.recorded_at.replace(tzinfo=timezone.utc)
                last_known = {
                    "gmp_amount": lr.gmp_amount,
                    "gmp_percentage": lr.gmp_percentage,
                    "source": lr.source,
                    "recorded_at": lr_dt.astimezone(ist_tz).isoformat()
                }

        if not valid_readings:
            return {
                "gmp_amount": None,
                "gmp_percentage": None,
                "sources_count": 0,
                "status": "missing",
                "single_source": False,
                "sources_disagree": False,
                "sources": [],
                "last_known": last_known
            }

        # 2. Get latest reading per source recorded in last 12 hours
        latest_by_source: Dict[str, IPOGmp] = {}
        for r in valid_readings:
            r_dt = r.recorded_at if r.recorded_at.tzinfo is not None else r.recorded_at.replace(tzinfo=timezone.utc)
            if r_dt >= fresh_cutoff:
                if r.source not in latest_by_source or r_dt > (
                    latest_by_source[r.source].recorded_at if latest_by_source[r.source].recorded_at.tzinfo is not None
                    else latest_by_source[r.source].recorded_at.replace(tzinfo=timezone.utc)
                ):
                    latest_by_source[r.source] = r

        fresh_readings = list(latest_by_source.values())

        if not fresh_readings:
            # Readings exist within 24h but are older than 12h (stale)
            return {
                "gmp_amount": None,
                "gmp_percentage": None,
                "sources_count": 0,
                "status": "stale",
                "single_source": False,
                "sources_disagree": False,
                "sources": [],
                "last_known": last_known
            }

        source_details = [
            {
                "source": r.source,
                "gmp_amount": r.gmp_amount,
                "gmp_percentage": r.gmp_percentage,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None
            }
            for r in fresh_readings
        ]

        # Single source case
        if len(fresh_readings) == 1:
            only = fresh_readings[0]
            return {
                "gmp_amount": only.gmp_amount,
                "gmp_percentage": only.gmp_percentage,
                "sources_count": 1,
                "status": "fresh",
                "single_source": True,
                "sources_disagree": False,
                "sources": source_details,
                "last_known": last_known
            }

        # Multiple sources case: calculate median
        amounts = [r.gmp_amount for r in fresh_readings]
        percentages = [r.gmp_percentage for r in fresh_readings]

        median_amt = statistics.median(amounts)
        median_pct = statistics.median(percentages)

        min_amt = min(amounts)
        max_amt = max(amounts)
        diff_amt = max_amt - min_amt

        # Disagreement rule:
        # >30% difference OR > Rs 25 when median < Rs 80
        sources_disagree = False
        if median_amt < 80.0:
            if diff_amt > 25.0:
                sources_disagree = True
            elif min_amt > 0 and (diff_amt / min_amt) > 0.30:
                sources_disagree = True
        else:
            if min_amt > 0 and (diff_amt / min_amt) > 0.30:
                sources_disagree = True

        return {
            "gmp_amount": round(median_amt, 2),
            "gmp_percentage": round(median_pct, 2),
            "sources_count": len(fresh_readings),
            "status": "fresh",
            "single_source": False,
            "sources_disagree": sources_disagree,
            "sources": source_details,
            "last_known": last_known
        }

    @classmethod
    async def get_ipo_consensus_gmp(
        cls,
        session: AsyncSession,
        ipo_id: int
    ) -> Dict[str, Any]:
        """Queries database for an IPO's recent GMP readings and returns consensus."""
        stmt = (
            select(IPOGmp)
            .where(IPOGmp.ipo_id == ipo_id)
            .order_by(IPOGmp.recorded_at.desc())
        )
        result = await session.execute(stmt)
        readings = result.scalars().all()
        return cls.calculate_consensus_from_readings(readings)
