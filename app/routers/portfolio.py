import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import require_auth, require_admin, get_current_user_id, limiter
from app.schemas.portfolio import (
    HoldingCreate, HoldingUpdate, HoldingResponse,
    TransactionCreate, TransactionResponse,
    PortfolioSummary, PortfolioSnapshotResponse, HoldingHistoryResponse,
    AngelOneDiagnoseResponse
)
from app.schemas.mutual_fund import CombinedNetWorthResponse
import app.services.portfolio_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["Portfolio"], dependencies=[Depends(require_auth)])


# ── Summary & Net Worth ──────────────────────────────────────────────────────

@router.get("/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Get full portfolio summary with live P&L for all holdings."""
    return await svc.get_portfolio_summary(db, user_id=user_id)


@router.get("/net-worth", response_model=CombinedNetWorthResponse)
async def portfolio_net_worth(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Get combined net worth across equity stocks and mutual funds with separate breakdowns."""
    from app.services.mutual_fund_service import get_combined_net_worth
    return await get_combined_net_worth(db, user_id=user_id)


# ── Holdings ─────────────────────────────────────────────────────────────────

@router.get("/holdings", response_model=list[HoldingResponse])
async def list_holdings(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """List all holdings (without live prices — use /summary for live data)."""
    return await svc.list_holdings(db, user_id=user_id)


@router.post("/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
async def add_holding(
    data: HoldingCreate,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Add a new stock holding. Also creates the initial BUY transaction."""
    existing = await svc.get_holding_by_symbol(db, data.symbol, data.exchange.value, user_id=user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Holding for {data.symbol.upper()} on {data.exchange.value} already exists. Use PATCH to update or add a transaction."
        )
    return await svc.create_holding(db, data, user_id=user_id)


@router.patch("/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(
    holding_id: int,
    data: HoldingUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Update holding details (quantity, avg price, company name)."""
    holding = await svc.update_holding(db, holding_id, data, user_id=user_id)
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    return holding


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    holding_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Delete a holding and all its transactions."""
    success = await svc.delete_holding(db, holding_id, user_id=user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Holding not found")


# ── Holding History & Snapshots ──────────────────────────────────────────────

@router.get("/holdings/{symbol}/history", response_model=HoldingHistoryResponse)
@limiter.limit("60/minute")
async def get_holding_history(
    request: Request,
    symbol: str,
    range: str = Query("3m", pattern="^(1m|3m|6m|1y)$", description="History range: 1m, 3m, 6m, 1y"),
    db: AsyncSession = Depends(get_db)
):
    """Daily OHLCV candlestick history from yfinance with EMA20, EMA50, RSI14, avg cost, and advisory levels."""
    return await svc.get_holding_history(symbol=symbol, range_str=range, db=db)


@router.get("/snapshots", response_model=list[PortfolioSnapshotResponse])
async def list_snapshots(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Get chronological portfolio valuation history snapshots."""
    return await svc.get_portfolio_snapshots(db, user_id=user_id)


# ── Transactions ─────────────────────────────────────────────────────────────

@router.post("/holdings/{holding_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def add_transaction(
    holding_id: int,
    data: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Record a BUY, SELL, DIVIDEND, BONUS or SPLIT transaction. BUY recalculates avg price automatically."""
    txn = await svc.add_transaction(db, holding_id, data, user_id=user_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Holding not found")
    return txn


@router.get("/holdings/{holding_id}/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    holding_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """Get full transaction history for a holding."""
    holding = await svc.get_holding(db, holding_id, user_id=user_id)
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    return holding.transactions


# ── Import: CSV / Excel ────────────────────────────────────────────────────────

@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(..., description="Holdings file (CSV / Excel) from Angel One, Zerodha, Groww, or Upstox"),
    password: Optional[str] = Form(None, description="Optional password for encrypted broker files (e.g. PAN card number)"),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Upload a holdings file (CSV or Excel .xlsx/.xls) exported from any major Indian broker.
    Auto-detects Angel One / Zerodha / Groww / Upstox format.
    Returns a summary of created / updated / skipped rows.
    """
    valid_exts = (".csv", ".xlsx", ".xls")
    if not any(file.filename.lower().endswith(ext) for ext in valid_exts):
        raise HTTPException(status_code=400, detail="Only .csv, .xlsx, or .xls files are supported.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB).")

    try:
        from app.services.csv_import_service import import_file_to_portfolio
        result = await import_file_to_portfolio(db, content, filename=file.filename, password=password, user_id=user_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("File import error")
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")


# ── Import: Angel One SmartAPI ────────────────────────────────────────────────

@router.get("/import/angelone/status")
async def angelone_status():
    """Check if Angel One SmartAPI credentials are configured."""
    from app.services.angelone_sync_service import _is_configured
    return {"configured": _is_configured()}


@router.get(
    "/import/angelone/diagnose",
    response_model=AngelOneDiagnoseResponse,
    dependencies=[Depends(require_admin)],
    summary="Diagnose Angel One connectivity, egress IPs, NTP offset, and login step status"
)
@limiter.limit("15/minute")
async def angelone_diagnose(request: Request):
    """
    Returns server egress IPv4/IPv6, system time offset vs NTP server,
    boolean presence of required environment variables, and last sync failure details.
    Restricted to authenticated admin users only.
    """
    from app.services.angelone_sync_service import diagnose_angelone
    return await diagnose_angelone()


@router.post("/import/angelone")
async def sync_angelone(db: AsyncSession = Depends(get_db)):
    """
    Pull your live holdings directly from Angel One SmartAPI.
    Requires ANGELONE_API_KEY, ANGELONE_CLIENT_ID, ANGELONE_PASSWORD
    (and optionally ANGELONE_TOTP_SECRET) in your .env file.
    """
    try:
        from app.services.angelone_sync_service import (
            sync_angelone_to_portfolio,
            _is_configured,
            AngelOneSyncError
        )
        if not _is_configured():
            raise HTTPException(
                status_code=400,
                detail={
                    "error_class": "unknown",
                    "message": "Angel One credentials are not configured. Add ANGELONE_API_KEY, ANGELONE_CLIENT_ID, and ANGELONE_PASSWORD in environment.",
                    "error_code": "NOT_CONFIGURED",
                    "step": "connect",
                }
            )
        result = await sync_angelone_to_portfolio(db)
        return result
    except HTTPException:
        raise
    except AngelOneSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_class": exc.error_class,
                "message": exc.user_message,
                "error_code": exc.error_code,
                "step": exc.step,
            }
        )
    except Exception as exc:
        logger.error("[AngelOne Sync] Uncaught sync error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_class": "unknown",
                "message": "Sync failed due to an unexpected server error.",
                "error_code": type(exc).__name__,
                "step": "unknown",
            }
        )


# ── AI Portfolio Doctor & Technical Advisory ─────────────────────────────────

@router.get("/advisory")
async def get_portfolio_advisory(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Get AI-powered technical advisory, candlestick patterns, RSI, Moving Averages,
    support/resistance levels, and action guidance to keep portfolio green.
    """
    summary = await svc.get_portfolio_summary(db, user_id=user_id)
    from app.services.portfolio_advisor_service import generate_portfolio_advisory
    holdings_dict = [h.model_dump() for h in summary.holdings]
    return await generate_portfolio_advisory(holdings_dict)


@router.post("/advisory/ask")
@limiter.limit("10/minute")
async def ask_portfolio_advisor(
    request: Request,
    data: dict,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Ask the AI Portfolio Doctor a question about technicals, candlestick patterns,
    stop-loss, or stock-specific actions, grounded in portfolio and active IPO context.
    """
    query = data.get("query", "").strip()[:500]
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    history = data.get("chat_history") or data.get("history") or data.get("messages") or []

    # 1. Fetch live portfolio summary
    summary = await svc.get_portfolio_summary(db, user_id=user_id)
    from app.services.portfolio_advisor_service import generate_portfolio_advisory, groq_answer_query
    from app.models.ipo import IPO, IPOStatus
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    holdings_dict = [h.model_dump() for h in summary.holdings]
    advisory_data = await generate_portfolio_advisory(holdings_dict)
    advisory_data["portfolio_summary"] = summary.model_dump()

    # Log context totals (without secrets) on each /ask call
    logger.info(
        "[Ask Endpoint Totals] query=%r total_invested=%.2f current_value=%.2f overall_pnl=%.2f (%.2f%%) holdings_count=%d",
        query,
        summary.total_invested,
        summary.current_value,
        summary.total_unrealized_pnl,
        summary.total_pnl_pct,
        summary.holdings_count
    )

    # 2. Fetch live & upcoming IPOs with subscriptions, GMP records, and scores
    ipos_data = []
    try:
        stmt = (
            select(IPO)
            .where(
                IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]),
                IPO.is_seed.is_(False)
            )
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score)
            )
            .order_by(IPO.open_date.asc().nulls_last())
        )
        active_ipos_objs = (await db.execute(stmt)).scalars().all()
        for ipo in active_ipos_objs:
            latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
            latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None

            if ipo.price_band_low and ipo.price_band_high:
                pband = f"₹{ipo.price_band_low:,.0f} - ₹{ipo.price_band_high:,.0f}"
            elif ipo.issue_price:
                pband = f"₹{ipo.issue_price:,.0f}"
            else:
                pband = "TBA"

            gmp_str = f"₹{latest_gmp.gmp_amount:,.0f} ({latest_gmp.gmp_percentage:.1f}%)" if latest_gmp else "N/A"
            sub_str = f"Total {latest_sub.total_multiple:.1f}x (QIB {latest_sub.qib_multiple or 0:.1f}x, Retail {latest_sub.retail_multiple or 0:.1f}x)" if latest_sub else "N/A"
            score_str = f"{ipo.score.composite_score:.1f}/100" if ipo.score else "N/A"
            rec_str = ipo.score.recommendation.value if ipo.score else "N/A"

            ipos_data.append({
                "symbol": ipo.symbol,
                "company_name": ipo.company_name,
                "status": ipo.status.value,
                "price_band": pband,
                "gmp": gmp_str,
                "subscription": sub_str,
                "score": score_str,
                "recommendation": rec_str
            })
    except Exception as e:
        logger.warning("Could not fetch active IPOs for advisory context: %s", e)

    answer, source = await groq_answer_query(
        query=query,
        advisory_data=advisory_data,
        chat_history=history,
        active_ipos=ipos_data,
        portfolio_summary=summary,
        db=db
    )
    return {"query": query, "answer": answer, "source": source}


@router.get("/scorecard")
async def get_swing_scorecard(db: AsyncSession = Depends(get_db)):
    """
    Get the technical diagnosis scorecard (total diagnoses, hit rate, target hits, stop hits).
    Shows collecting progress until at least 30 closed diagnoses exist.
    """
    from app.services.technical_analysis_service import get_technical_diagnosis_scorecard
    return await get_technical_diagnosis_scorecard(db)


@router.get("/technical-scorecard")
async def get_technical_scorecard_endpoint(db: AsyncSession = Depends(get_db)):
    """
    Direct endpoint for technical diagnosis scorecard.
    """
    from app.services.technical_analysis_service import get_technical_diagnosis_scorecard
    return await get_technical_diagnosis_scorecard(db)



