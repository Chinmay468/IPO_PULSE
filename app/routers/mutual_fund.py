"""
Mutual Funds router:
Handles CAS PDF imports, holdings, transactions, NAV history, and portfolio summary.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import require_auth, get_current_user_id, limiter
from app.schemas.mutual_fund import (
    MFSummaryResponse,
    MFSchemeHistoryResponse,
    MFHoldingCreate,
    MFHoldingUpdate,
    MFHoldingItemResponse,
    MFTransactionCreate,
    MFTransactionResponse,
    CASImportResponse
)
from app.services.mf_cas_parser_service import parse_cas_pdf_bytes, import_parsed_cas
from app.services.mf_nav_service import sync_all_scheme_navs
import app.services.mutual_fund_service as mf_svc

router = APIRouter(prefix="/portfolio/mf", tags=["Mutual Funds"], dependencies=[Depends(require_auth)])


@router.post("/import/cas", response_model=CASImportResponse)
@limiter.limit("10/minute")
async def import_cas_pdf(
    request: Request,
    file: UploadFile = File(..., description="CAMS / KFintech Consolidated Account Statement (CAS) PDF"),
    password: Optional[str] = Form(None, description="Optional password if CAS PDF is encrypted"),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Import CAS PDF statement in memory using casparser.
    Never saves the file to disk. Never logs PAN, password, or folio numbers.
    De-duplicates transactions on (folio hash, date, units, amount).
    Scoped by user_id.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload a PDF file."
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds the 10 MB maximum limit."
        )

    try:
        # In-memory parse
        parsed_data = parse_cas_pdf_bytes(content, password=password)
        # Import and de-duplicate scoped by user_id
        summary = await import_parsed_cas(db, parsed_data, user_id=user_id)
        # Background/sync NAV check
        try:
            await sync_all_scheme_navs(db, force_refresh_amfi=False)
        except Exception:
            pass

        return CASImportResponse(
            status="success",
            schemes_created=summary["schemes_created"],
            holdings_created=summary["holdings_created"],
            transactions_imported=summary["transactions_imported"],
            transactions_skipped=summary["transactions_skipped"],
            message=f"Import complete: {summary['transactions_imported']} transactions imported, {summary['transactions_skipped']} skipped (already present)."
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except Exception as exc:
        logger.exception("[CAS Import Exception] Failed to process CAS: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process CAS statement: {type(exc).__name__} - {str(exc)}"
        )


@router.get("/summary", response_model=MFSummaryResponse)
async def get_mutual_funds_summary(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Get overall mutual funds summary, XIRR, category/AMC allocations, and holdings list.
    Unpriced holdings are excluded from portfolio value and counted.
    Scoped by user_id.
    """
    return await mf_svc.get_mf_summary(db, user_id=user_id)


@router.get("/{scheme_id}/history", response_model=MFSchemeHistoryResponse)
async def get_mutual_fund_nav_history(scheme_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get historical daily NAVs for a specific scheme.
    """
    try:
        return await mf_svc.get_scheme_nav_history(db, scheme_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheme not found")


@router.post("/sync-navs")
@limiter.limit("10/minute")
async def trigger_mf_nav_sync(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Manually trigger AMFI daily NAV file download and update schemes.
    """
    res = await sync_all_scheme_navs(db, force_refresh_amfi=True)
    return {"status": "success", "result": res}


@router.post("/holdings", response_model=MFHoldingItemResponse)
async def create_holding(
    payload: MFHoldingCreate,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Manually add a mutual fund holding scoped by user_id.
    """
    return await mf_svc.create_manual_holding(db, payload, user_id=user_id)


@router.put("/holdings/{holding_id}")
async def update_holding(holding_id: int, payload: MFHoldingUpdate, db: AsyncSession = Depends(get_db)):
    """
    Manually edit a mutual fund holding units or masked folio.
    """
    ok = await mf_svc.update_manual_holding(db, holding_id, payload)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return {"status": "success", "message": "Holding updated"}


@router.delete("/holdings/{holding_id}")
async def delete_holding(holding_id: int, db: AsyncSession = Depends(get_db)):
    """
    Delete a mutual fund holding and its transactions.
    """
    ok = await mf_svc.delete_holding(db, holding_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return {"status": "success", "message": "Holding deleted"}


@router.post("/holdings/{holding_id}/transactions", response_model=MFTransactionResponse)
async def add_transaction(holding_id: int, payload: MFTransactionCreate, db: AsyncSession = Depends(get_db)):
    """
    Add a transaction to a mutual fund holding.
    """
    try:
        return await mf_svc.add_holding_transaction(db, holding_id, payload)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: int, db: AsyncSession = Depends(get_db)):
    """
    Delete a mutual fund transaction.
    """
    ok = await mf_svc.delete_holding_transaction(db, transaction_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return {"status": "success", "message": "Transaction deleted"}
