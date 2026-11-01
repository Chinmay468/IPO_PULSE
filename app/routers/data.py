"""
Data Layer Router.
Handles price history exports (CSV/XLSX/Parquet), backfill triggers,
and data quality / coverage reporting.
"""

import logging
from datetime import date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from starlette.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.auth import require_auth, require_admin, limiter
from app.models.price_history import DataIssue
from app.schemas.portfolio import DataCoverageItem, DataIssueItem, BackfillResponse
import app.services.price_history_service as ph_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["Data Layer"], dependencies=[Depends(require_auth)])


@router.get("/prices/export")
@limiter.limit("15/minute")
async def export_prices(
    request: Request,
    symbol: str = Query(..., description="Stock symbol (e.g. RELIANCE, TCS)"),
    from_date: Optional[date] = Query(None, alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, alias="to", description="End date (YYYY-MM-DD)"),
    format: str = Query("csv", pattern="^(csv|xlsx|parquet)$", description="File format: csv, xlsx, parquet"),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream historical daily prices for a symbol without saving files on the server.
    Supports CSV, XLSX, and Parquet formats.
    """
    try:
        buffer, media_type, filename = await ph_svc.export_price_history_stream(
            db=db,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            format_type=format
        )
    except Exception as exc:
        logger.error("[Export] Failed to generate %s export for %s: %s", format, symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate price export: {str(exc)}"
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(buffer, media_type=media_type, headers=headers)


@router.post("/prices/backfill", response_model=BackfillResponse)
@limiter.limit("5/minute")
async def trigger_price_backfill(
    request: Request,
    years: int = Query(5, ge=1, le=10, description="Years of historical candles to backfill (max 10)"),
    sleep_sec: float = Query(0.5, ge=0.1, le=5.0, description="Sleep between symbols to prevent rate limiting"),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin endpoint to backfill up to 5 years of daily candles from yfinance
    for all portfolio holdings and default watchlist symbols.
    Handles listings with short history, retries with backoff, and validates every candle.
    """
    try:
        result = await ph_svc.backfill_all_symbols(
            db=db,
            years=years,
            sleep_sec=sleep_sec
        )
        return result
    except Exception as exc:
        logger.error("[Backfill] Backfill failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backfill execution failed: {str(exc)}"
        )


@router.get("/quality/coverage", response_model=List[DataCoverageItem])
@limiter.limit("30/minute")
async def get_data_coverage(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns data coverage summary per tracked symbol including first date,
    last date, total candle count, and missing trading days.
    """
    return await ph_svc.get_data_coverage_stats(db)


@router.get("/quality/issues", response_model=List[DataIssueItem])
@limiter.limit("30/minute")
async def get_data_issues(
    request: Request,
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    unresolved_only: bool = Query(True, description="Filter only unresolved flags"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns validation issues and review flags (e.g. >40% jumps, trading gaps, corrupt candles).
    """
    return await ph_svc.get_data_issues_list(
        db=db,
        symbol=symbol,
        unresolved_only=unresolved_only,
        limit=limit
    )


@router.post("/quality/issues/{issue_id}/resolve")
async def resolve_data_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Marks a data quality review issue as resolved."""
    res = await db.execute(select(DataIssue).where(DataIssue.id == issue_id))
    issue = res.scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Data issue not found")

    issue.resolved = True
    await db.commit()
    return {"status": "success", "issue_id": issue_id, "resolved": True}
