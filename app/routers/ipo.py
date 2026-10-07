from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ipo import IPOStatus, IPOType, RecommendationType
from app.schemas.ipo import (
    IPOCreate,
    IPOUpdate,
    IPOResponse,
    IPODetailResponse,
    IPOListResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    GMPCreate,
    GMPResponse,
    ScoreResponse
)
from datetime import date
from app.services.ipo_service import IPOService
from app.services.scoring_service import ScoringService
from app.auth import require_auth

router = APIRouter(prefix="/ipos", tags=["IPOs & Suggestions"])


def _check_apply_eligibility(ipo) -> tuple[bool, bool]:
    """
    Returns (can_apply, is_pre_apply).
    - can_apply: True ONLY when IPO is LIVE or in Pre-Apply window.
    - is_pre_apply: True if UPCOMING and within 2 days of open_date.
    - LISTED or CLOSED IPOs are strictly NEVER biddable.
    """
    if ipo.status in [IPOStatus.LISTED, IPOStatus.CLOSED]:
        return False, False

    if ipo.status == IPOStatus.LIVE:
        return True, False

    if ipo.status == IPOStatus.UPCOMING:
        today = date.today()
        if ipo.open_date:
            days_to_open = (ipo.open_date - today).days
            if 0 <= days_to_open <= 2:
                return True, True
        return False, False

    return False, False


def _format_ipo_response(ipo) -> IPOResponse:
    resp = IPOResponse.model_validate(ipo)
    if ipo.gmp_records and len(ipo.gmp_records) > 0:
        resp.latest_gmp = GMPResponse.model_validate(ipo.gmp_records[0])
    if ipo.subscriptions and len(ipo.subscriptions) > 0:
        resp.latest_subscription = SubscriptionResponse.model_validate(ipo.subscriptions[0])
    if ipo.score:
        resp.score = ScoreResponse.model_validate(ipo.score)

    can_apply, is_pre_apply = _check_apply_eligibility(ipo)
    resp.can_apply = can_apply
    resp.is_pre_apply = is_pre_apply
    resp.angelone_apply_url = f"/api/v1/ipos/{ipo.id}/apply/angelone" if can_apply else None
    return resp


def _format_ipo_detail_response(ipo) -> IPODetailResponse:
    detail = IPODetailResponse.model_validate(ipo)
    if ipo.gmp_records and len(ipo.gmp_records) > 0:
        detail.latest_gmp = GMPResponse.model_validate(ipo.gmp_records[0])
    if ipo.subscriptions and len(ipo.subscriptions) > 0:
        detail.latest_subscription = SubscriptionResponse.model_validate(ipo.subscriptions[0])
    if ipo.score:
        detail.score = ScoreResponse.model_validate(ipo.score)

    can_apply, is_pre_apply = _check_apply_eligibility(ipo)
    detail.can_apply = can_apply
    detail.is_pre_apply = is_pre_apply
    detail.angelone_apply_url = f"/api/v1/ipos/{ipo.id}/apply/angelone" if can_apply else None
    return detail


@router.get("", response_model=IPOListResponse, summary="List all IPOs with filtering and recommendations")
async def list_ipos(
    status: Optional[IPOStatus] = Query(None, description="Filter by status: UPCOMING, LIVE, CLOSED, LISTED"),
    ipo_type: Optional[IPOType] = Query(None, description="Filter by type: MAINBOARD or SME"),
    recommendation: Optional[RecommendationType] = Query(None, description="Filter by suggestion: STRONG APPLY, APPLY, NEUTRAL, AVOID"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Filter by minimum composite score"),
    search: Optional[str] = Query(None, description="Search across symbol or company name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    items, total = await IPOService.list_ipos(
        session=db,
        status=status,
        ipo_type=ipo_type,
        recommendation=recommendation,
        min_score=min_score,
        search=search,
        skip=skip,
        limit=limit
    )
    formatted_items = [_format_ipo_response(ipo) for ipo in items]
    return IPOListResponse(total=total, items=formatted_items)


@router.get("/symbol/{symbol}", response_model=IPODetailResponse, summary="Get IPO details by ticker symbol")
async def get_ipo_by_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_symbol(db, symbol)
    if not ipo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IPO with symbol '{symbol}' not found"
        )
    return _format_ipo_detail_response(ipo)


@router.get("/{id}", response_model=IPODetailResponse, summary="Get IPO complete details with history and score")
async def get_ipo(id: int, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IPO with id {id} not found"
        )
    return _format_ipo_detail_response(ipo)


@router.post("", response_model=IPOResponse, status_code=status.HTTP_201_CREATED, summary="Create an IPO master record", dependencies=[Depends(require_auth)])
async def create_ipo(data: IPOCreate, db: AsyncSession = Depends(get_db)):
    existing = await IPOService.get_ipo_by_symbol(db, data.symbol)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"IPO with symbol '{data.symbol}' already exists"
        )
    ipo = await IPOService.create_ipo(db, data)
    return _format_ipo_response(ipo)


@router.put("/{id}", response_model=IPOResponse, summary="Update an existing IPO record", dependencies=[Depends(require_auth)])
async def update_ipo(id: int, data: IPOUpdate, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IPO with id {id} not found"
        )
    updated = await IPOService.update_ipo(db, ipo, data)
    return _format_ipo_response(updated)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an IPO record", dependencies=[Depends(require_auth)])
async def delete_ipo(id: int, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IPO with id {id} not found"
        )
    await IPOService.delete_ipo(db, ipo)
    return None


@router.post("/{id}/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED, summary="Record a new subscription snapshot", dependencies=[Depends(require_auth)])
async def add_subscription(id: int, data: SubscriptionCreate, db: AsyncSession = Depends(get_db)):
    try:
        sub = await IPOService.add_subscription(db, id, data)
        return sub
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{id}/gmp", response_model=GMPResponse, status_code=status.HTTP_201_CREATED, summary="Record a new GMP update", dependencies=[Depends(require_auth)])
async def add_gmp(id: int, data: GMPCreate, db: AsyncSession = Depends(get_db)):
    try:
        gmp = await IPOService.add_gmp(db, id, data)
        return gmp
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{id}/score", response_model=ScoreResponse, summary="Get latest recommendation and composite score")
async def get_score(id: int, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IPO with id {id} not found")
    if not ipo.score:
        score = await IPOService.recalculate_score(db, id)
        return score
    return ipo.score


@router.post("/{id}/score/recalculate", response_model=ScoreResponse, summary="Recalculate composite score on-demand", dependencies=[Depends(require_auth)])
async def recalculate_score(id: int, db: AsyncSession = Depends(get_db)):
    try:
        score = await IPOService.recalculate_score(db, id)
        return score
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{id}/score/breakdown", summary="Get detailed pillar-by-pillar score breakdown and reasons")
async def get_score_breakdown(id: int, db: AsyncSession = Depends(get_db)):
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IPO with id {id} not found")

    latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
    latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
    score_result = ScoringService.calculate_score(ipo, latest_sub, latest_gmp)

    rec_val = score_result["recommendation"]
    if hasattr(rec_val, "value"):
        rec_val = rec_val.value

    return {
        "ipo_id": ipo.id,
        "symbol": ipo.symbol,
        "company_name": ipo.company_name,
        "composite_score": score_result["composite_score"],
        "recommendation": rec_val,
        "pillars": score_result["rationale"]["pillars"],
        "positive_factors": score_result["rationale"]["positive_factors"],
        "risk_factors": score_result["rationale"]["risk_factors"]
    }


import re


def _get_angelone_target_url(company_name: str) -> str:
    """
    Returns the canonical Angel One live IPO application portal URL:
    https://www.angelone.in/ipo-app/
    This takes authenticated users directly to their active bidding and application dashboard.
    """
    return "https://www.angelone.in/ipo-app/"




@router.get("/{id}/apply/angelone", summary="Redirect to live Angel One IPO application portal")
async def redirect_angelone_apply(id: int, db: AsyncSession = Depends(get_db)):
    """
    Redirects the user directly to the Angel One IPO portal to apply for this issue.
    Only permitted for LIVE or Pre-Apply open issues.
    """
    ipo = await IPOService.get_ipo_by_id(db, id)
    if not ipo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IPO with id {id} not found")
    
    can_apply, _ = _check_apply_eligibility(ipo)
    if not can_apply:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bidding unavailable for {ipo.symbol}. The issue is {ipo.status.value.lower()} and no longer accepting bids."
        )

    target_url = _get_angelone_target_url(ipo.company_name)
    return RedirectResponse(url=target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/symbol/{symbol}/apply/angelone", summary="Redirect to live Angel One IPO application portal by ticker symbol")
async def redirect_angelone_apply_by_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    """
    Redirects to the Angel One IPO portal matching ticker symbol.
    Only permitted for LIVE or Pre-Apply open issues.
    """
    ipo = await IPOService.get_ipo_by_symbol(db, symbol)
    if not ipo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IPO with symbol '{symbol}' not found")
    
    can_apply, _ = _check_apply_eligibility(ipo)
    if not can_apply:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bidding unavailable for {ipo.symbol}. The issue is {ipo.status.value.lower()} and no longer accepting bids."
        )

    target_url = _get_angelone_target_url(ipo.company_name)
    return RedirectResponse(url=target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


