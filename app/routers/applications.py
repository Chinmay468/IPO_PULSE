from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_auth, hash_password_secure
from app.database import get_db
from app.models.ipo import IPO, IPOApplication
from app.models.user import User

router = APIRouter(prefix="/applications", tags=["IPO Applications"])


class ApplicationCreateRequest(BaseModel):
    ipo_id: int = Field(..., description="ID of the IPO applied for")
    applicant_name: str = Field("Self", max_length=100, description="Account / Family member label (e.g. Self, Mom, Dad)")
    category: str = Field("RETAIL", max_length=50, description="Application category: RETAIL, SHNI, BHNI, EMPLOYEE, SHAREHOLDER")
    lots_applied: int = Field(1, ge=1, le=500, description="Number of lots applied")
    bid_price: Optional[float] = Field(None, gt=0, description="Bid price per share (defaults to IPO issue_price or price_band_high)")
    status: str = Field("APPLIED", description="APPLIED, ALLOTTED, NOT_ALLOTTED, SOLD")
    lots_allotted: int = Field(0, ge=0, le=500, description="Number of lots allotted (if status is ALLOTTED or SOLD)")
    selling_price: Optional[float] = Field(None, gt=0, description="Exit / selling price per share (if SOLD)")
    notes: Optional[str] = Field(None, max_length=255, description="Optional notes or UPI reference")


class ApplicationUpdateRequest(BaseModel):
    applicant_name: Optional[str] = Field(None, max_length=100)
    category: Optional[str] = Field(None, max_length=50)
    lots_applied: Optional[int] = Field(None, ge=1, le=500)
    bid_price: Optional[float] = Field(None, gt=0)
    status: Optional[str] = Field(None, description="APPLIED, ALLOTTED, NOT_ALLOTTED, SOLD")
    lots_allotted: Optional[int] = Field(None, ge=0, le=500)
    selling_price: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=255)


class ApplicationItemResponse(BaseModel):
    id: int
    user_id: int
    ipo_id: int
    symbol: str
    company_name: str
    ipo_type: str
    ipo_status: str
    lot_size: int
    issue_price: Optional[float] = None
    listing_price: Optional[float] = None
    latest_gmp: float = 0.0
    latest_gmp_pct: float = 0.0
    applicant_name: str
    category: str
    lots_applied: int
    shares_applied: int
    bid_price: float
    amount_blocked: float
    status: str
    lots_allotted: int
    shares_allotted: int
    selling_price: Optional[float] = None
    realized_profit: Optional[float] = None
    estimated_profit: float = 0.0
    profit_pct: float = 0.0
    notes: Optional[str] = None
    applied_at: datetime
    updated_at: datetime


class ApplicationSummaryMetrics(BaseModel):
    total_applications: int = 0
    active_applications: int = 0
    active_blocked_capital: float = 0.0
    allotted_count: int = 0
    not_allotted_count: int = 0
    decided_count: int = 0
    hit_ratio_pct: float = 0.0
    total_realized_profit: float = 0.0
    expected_gmp_profit: float = 0.0


class ApplicationListResponse(BaseModel):
    summary: ApplicationSummaryMetrics
    items: List[ApplicationItemResponse]


VALID_STATUSES = {"APPLIED", "ALLOTTED", "NOT_ALLOTTED", "SOLD"}
VALID_CATEGORIES = {"RETAIL", "SHNI", "BHNI", "EMPLOYEE", "SHAREHOLDER"}


async def _resolve_user_id(payload: dict, db: AsyncSession) -> int:
    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            uid = int(user_id)
            res = await db.execute(select(User.id).where(User.id == uid))
            if res.scalar_one_or_none() is not None:
                return uid
        except (ValueError, TypeError):
            pass

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user token")

    res = await db.execute(select(User).where(User.username == sub))
    user = res.scalar_one_or_none()
    if not user:
        user = User(
            username=sub,
            hashed_password=hash_password_secure("auto-provisioned"),
            is_active=True,
            is_superuser=bool(payload.get("is_superuser", False)),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user.id


def _build_item_response(app_rec: IPOApplication, ipo: IPO) -> ApplicationItemResponse:
    lot_size = ipo.lot_size or max(1, int(app_rec.shares_applied / max(1, app_rec.lots_applied)))
    latest_gmp = 0.0
    latest_gmp_pct = 0.0
    if ipo.gmp_records:
        sorted_gmp = sorted(
            ipo.gmp_records,
            key=lambda g: g.recorded_at or datetime.min,
            reverse=True
        )
        latest_gmp = float(sorted_gmp[0].gmp_amount or 0.0)
        latest_gmp_pct = float(sorted_gmp[0].gmp_percentage or 0.0)

    # Calculate estimated / realized profit
    estimated_profit = 0.0
    profit_pct = 0.0
    realized_profit = app_rec.realized_profit

    if app_rec.status in ("ALLOTTED", "SOLD"):
        shares = app_rec.shares_allotted or (max(1, app_rec.lots_allotted or 1) * lot_size)
        exit_price = app_rec.selling_price or ipo.listing_price
        if exit_price is not None:
            realized_profit = round((exit_price - app_rec.bid_price) * shares, 2)
            estimated_profit = realized_profit
            if app_rec.bid_price > 0:
                profit_pct = round(((exit_price - app_rec.bid_price) / app_rec.bid_price) * 100.0, 2)
        else:
            # Allotted but not yet listed: estimate via GMP
            estimated_profit = round(latest_gmp * shares, 2)
            if app_rec.bid_price > 0:
                profit_pct = round((latest_gmp / app_rec.bid_price) * 100.0, 2)
    elif app_rec.status == "APPLIED":
        # Potential gain on 1 lot (for Retail) or applied shares if allotted at current GMP
        est_shares = lot_size if app_rec.category == "RETAIL" else app_rec.shares_applied
        estimated_profit = round(latest_gmp * est_shares, 2)
        if app_rec.bid_price > 0:
            profit_pct = round((latest_gmp / app_rec.bid_price) * 100.0, 2)

    ipo_type_str = ipo.ipo_type.value if hasattr(ipo.ipo_type, "value") else str(ipo.ipo_type)
    ipo_status_str = ipo.status.value if hasattr(ipo.status, "value") else str(ipo.status)

    return ApplicationItemResponse(
        id=app_rec.id,
        user_id=app_rec.user_id,
        ipo_id=app_rec.ipo_id,
        symbol=ipo.symbol,
        company_name=ipo.company_name,
        ipo_type=ipo_type_str,
        ipo_status=ipo_status_str,
        lot_size=lot_size,
        issue_price=ipo.issue_price or ipo.price_band_high,
        listing_price=ipo.listing_price,
        latest_gmp=latest_gmp,
        latest_gmp_pct=latest_gmp_pct,
        applicant_name=app_rec.applicant_name,
        category=app_rec.category,
        lots_applied=app_rec.lots_applied,
        shares_applied=app_rec.shares_applied,
        bid_price=app_rec.bid_price,
        amount_blocked=app_rec.amount_blocked,
        status=app_rec.status,
        lots_allotted=app_rec.lots_allotted,
        shares_allotted=app_rec.shares_allotted,
        selling_price=app_rec.selling_price,
        realized_profit=realized_profit,
        estimated_profit=estimated_profit,
        profit_pct=profit_pct,
        notes=app_rec.notes,
        applied_at=app_rec.applied_at,
        updated_at=app_rec.updated_at,
    )


@router.get("", response_model=ApplicationListResponse, summary="List current user's IPO applications and summary metrics")
async def list_my_applications(
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(payload, db)
    stmt = (
        select(IPOApplication)
        .where(IPOApplication.user_id == user_id)
        .options(selectinload(IPOApplication.ipo).selectinload(IPO.gmp_records))
        .order_by(IPOApplication.applied_at.desc(), IPOApplication.id.desc())
    )
    records = (await db.execute(stmt)).scalars().all()

    items: List[ApplicationItemResponse] = []
    active_count = 0
    active_blocked = 0.0
    allotted_count = 0
    not_allotted_count = 0
    total_realized = 0.0
    expected_gmp = 0.0

    for rec in records:
        if not rec.ipo:
            continue
        item = _build_item_response(rec, rec.ipo)
        items.append(item)

        if item.status == "APPLIED":
            active_count += 1
            active_blocked += item.amount_blocked
            expected_gmp += item.estimated_profit
        elif item.status in ("ALLOTTED", "SOLD"):
            allotted_count += 1
            if item.realized_profit is not None:
                total_realized += item.realized_profit
            else:
                expected_gmp += item.estimated_profit
        elif item.status == "NOT_ALLOTTED":
            not_allotted_count += 1

    decided_count = allotted_count + not_allotted_count
    hit_ratio = round((allotted_count / decided_count) * 100.0, 1) if decided_count > 0 else 0.0

    summary = ApplicationSummaryMetrics(
        total_applications=len(items),
        active_applications=active_count,
        active_blocked_capital=round(active_blocked, 2),
        allotted_count=allotted_count,
        not_allotted_count=not_allotted_count,
        decided_count=decided_count,
        hit_ratio_pct=hit_ratio,
        total_realized_profit=round(total_realized, 2),
        expected_gmp_profit=round(expected_gmp, 2),
    )
    return ApplicationListResponse(summary=summary, items=items)


@router.post("", response_model=ApplicationItemResponse, status_code=status.HTTP_201_CREATED, summary="Log a new IPO application")
async def create_application(
    body: ApplicationCreateRequest,
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(payload, db)

    stmt_ipo = select(IPO).where(IPO.id == body.ipo_id).options(selectinload(IPO.gmp_records))
    ipo = (await db.execute(stmt_ipo)).scalar_one_or_none()
    if not ipo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IPO not found")

    clean_status = body.status.strip().upper()
    if clean_status not in VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status. Must be one of {sorted(VALID_STATUSES)}")

    clean_category = body.category.strip().upper()
    if clean_category not in VALID_CATEGORIES:
        clean_category = "RETAIL"

    lot_size = ipo.lot_size or 1
    bid_price = body.bid_price or ipo.issue_price or ipo.price_band_high or ipo.price_band_low or 100.0
    shares_applied = body.lots_applied * lot_size
    amount_blocked = round(shares_applied * bid_price, 2)

    lots_allotted = body.lots_allotted
    if clean_status in ("ALLOTTED", "SOLD") and lots_allotted == 0:
        lots_allotted = 1 if clean_category == "RETAIL" else body.lots_applied
    elif clean_status in ("APPLIED", "NOT_ALLOTTED"):
        lots_allotted = 0

    shares_allotted = lots_allotted * lot_size
    selling_price = body.selling_price
    realized_profit = None
    if clean_status in ("ALLOTTED", "SOLD"):
        exit_p = selling_price or ipo.listing_price
        if exit_p is not None and shares_allotted > 0:
            realized_profit = round((exit_p - bid_price) * shares_allotted, 2)

    app_rec = IPOApplication(
        user_id=user_id,
        ipo_id=ipo.id,
        applicant_name=body.applicant_name.strip() or "Self",
        category=clean_category,
        lots_applied=body.lots_applied,
        shares_applied=shares_applied,
        bid_price=bid_price,
        amount_blocked=amount_blocked,
        status=clean_status,
        lots_allotted=lots_allotted,
        shares_allotted=shares_allotted,
        selling_price=selling_price,
        realized_profit=realized_profit,
        notes=body.notes.strip() if body.notes else None,
    )
    db.add(app_rec)
    await db.commit()
    await db.refresh(app_rec)

    return _build_item_response(app_rec, ipo)


@router.put("/{app_id}", response_model=ApplicationItemResponse, summary="Update an IPO application status or exit details")
async def update_application(
    app_id: int,
    body: ApplicationUpdateRequest,
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(payload, db)
    stmt = (
        select(IPOApplication)
        .where(IPOApplication.id == app_id, IPOApplication.user_id == user_id)
        .options(selectinload(IPOApplication.ipo).selectinload(IPO.gmp_records))
    )
    app_rec = (await db.execute(stmt)).scalar_one_or_none()
    if not app_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    ipo = app_rec.ipo
    lot_size = (ipo.lot_size if ipo else None) or max(1, int(app_rec.shares_applied / max(1, app_rec.lots_applied)))

    if body.applicant_name is not None:
        app_rec.applicant_name = body.applicant_name.strip() or "Self"
    if body.category is not None:
        cat = body.category.strip().upper()
        if cat in VALID_CATEGORIES:
            app_rec.category = cat
    if body.lots_applied is not None:
        app_rec.lots_applied = body.lots_applied
    if body.bid_price is not None:
        app_rec.bid_price = body.bid_price

    app_rec.shares_applied = app_rec.lots_applied * lot_size
    app_rec.amount_blocked = round(app_rec.shares_applied * app_rec.bid_price, 2)

    if body.status is not None:
        clean_status = body.status.strip().upper()
        if clean_status not in VALID_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status. Must be one of {sorted(VALID_STATUSES)}")
        app_rec.status = clean_status

    if body.lots_allotted is not None:
        app_rec.lots_allotted = body.lots_allotted
    elif app_rec.status in ("ALLOTTED", "SOLD") and app_rec.lots_allotted == 0:
        app_rec.lots_allotted = 1 if app_rec.category == "RETAIL" else app_rec.lots_applied
    elif app_rec.status in ("APPLIED", "NOT_ALLOTTED"):
        app_rec.lots_allotted = 0

    app_rec.shares_allotted = app_rec.lots_allotted * lot_size

    if body.selling_price is not None:
        app_rec.selling_price = body.selling_price

    if body.notes is not None:
        app_rec.notes = body.notes.strip() or None

    # Recalculate realized profit
    if app_rec.status in ("ALLOTTED", "SOLD") and app_rec.shares_allotted > 0:
        exit_p = app_rec.selling_price or (ipo.listing_price if ipo else None)
        if exit_p is not None:
            app_rec.realized_profit = round((exit_p - app_rec.bid_price) * app_rec.shares_allotted, 2)
        else:
            app_rec.realized_profit = None
    else:
        app_rec.realized_profit = None

    await db.commit()
    await db.refresh(app_rec)
    return _build_item_response(app_rec, ipo)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a tracked IPO application")
async def delete_application(
    app_id: int,
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(payload, db)
    stmt = select(IPOApplication).where(IPOApplication.id == app_id, IPOApplication.user_id == user_id)
    app_rec = (await db.execute(stmt)).scalar_one_or_none()
    if not app_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    await db.delete(app_rec)
    await db.commit()
    return None
