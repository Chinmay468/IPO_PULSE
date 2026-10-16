import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.database import get_db
from app.models.ipo import IPO, IPOStatus
from app.core.registrars import CanonicalRegistrar, DEFAULT_REGISTRAR_URLS, normalize_registrar_name
from app.schemas.ipo import (
    RegistrarCompanyItem,
    AllotmentQueryRequest,
    AllotmentResultResponse,
    AllotmentIPOItem,
    AllotmentIPOsResponse,
)
from app.services.registrar_proxy import RegistrarProxyService, mask_identifier
from app.auth import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/allotment", tags=["Registrar Allotment Proxy"])


@router.get(
    "/ipos",
    response_model=AllotmentIPOsResponse,
    summary="List all IPOs with registrar allotment details and supported_inline flag"
)
async def list_allotment_ipos(
    q: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns all IPOs (upcoming, live, closed, past) from the database with:
    name, status, registrar, allotment_date, and supported_inline flag (True ONLY for Link Intime).
    Allows search filtering by query substring (q) and lifecycle status.
    If database has no matching records, returns an empty list with a clear message.
    """
    query = select(IPO)

    # 1. Search filter across company name and symbol
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(IPO.company_name.ilike(term), IPO.symbol.ilike(term)))

    # 2. Lifecycle status filter
    if status and status.strip():
        st_clean = status.strip().upper()
        matched_enum = next((e for e in IPOStatus if e.value == st_clean or e.name == st_clean), None)
        if matched_enum:
            query = query.where(IPO.status == matched_enum)

    # 3. Ordering: recent & active first, then ID
    query = query.order_by(IPO.open_date.desc().nullslast(), IPO.id.desc()).limit(min(max(limit, 1), 500))

    result = await db.execute(query)
    ipos = result.scalars().all()

    items: List[AllotmentIPOItem] = []
    for ipo in ipos:
        norm_reg = normalize_registrar_name(ipo.registrar_name)
        is_inline = bool(norm_reg == CanonicalRegistrar.LINKINTIME)
        allot_url = ipo.registrar_allotment_url or (DEFAULT_REGISTRAR_URLS.get(norm_reg) if norm_reg else None)

        items.append(
            AllotmentIPOItem(
                id=ipo.id,
                symbol=ipo.symbol,
                company_name=ipo.company_name,
                status=ipo.status.value if hasattr(ipo.status, "value") else str(ipo.status),
                ipo_type=ipo.ipo_type.value if hasattr(ipo.ipo_type, "value") else str(ipo.ipo_type),
                registrar_name=norm_reg or ipo.registrar_name,
                registrar_code=ipo.registrar_code,
                registrar_allotment_url=allot_url,
                allotment_date=ipo.allotment_date,
                supported_inline=is_inline,
                open_date=ipo.open_date,
                close_date=ipo.close_date,
                listing_date=ipo.listing_date,
            )
        )

    msg = None
    if not items:
        msg = "No IPOs found in the database matching your search." if (q or status) else "No IPO data available."

    return AllotmentIPOsResponse(
        ipos=items,
        total=len(items),
        message=msg
    )


@router.get(
    "/linkintime/companies",
    response_model=List[RegistrarCompanyItem],
    summary="List active companies available on Link Intime portal"
)
async def get_linkintime_companies():
    """
    Returns the list of IPO companies currently available on Link Intime
    for allotment status queries. Returns empty list if temporarily unreachable.
    """
    companies = await RegistrarProxyService.get_linkintime_companies()
    return companies


@router.post(
    "/linkintime/check",
    response_model=AllotmentResultResponse,
    summary="Query investor IPO allotment status via Link Intime proxy"
)
@limiter.limit("30/minute")
async def check_allotment(request: Request, req_body: AllotmentQueryRequest):
    """
    Proxies allotment verification to Link Intime using PAN, Application Number, or DP ID.
    Returns standardized status: ALLOTTED, NOT_ALLOTTED, NOT_FOUND, or ERROR.
    Rate limited to 30 requests per minute per IP.
    Guarantees privacy: never logs, stores, or returns raw sensitive identifiers.
    """
    if not req_body.query_value or len(req_body.query_value.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query_value must be a valid identifier with at least 3 characters"
        )

    result = await RegistrarProxyService.query_allotment(req_body)
    return result


@router.get(
    "/linkintime/sync-mappings",
    summary="Trigger on-demand sync of Link Intime companies with database IPOs"
)
async def sync_linkintime_mappings():
    """
    Manually triggers daily Link Intime company mapping job and returns mapped & unmatched companies.
    """
    from app.services.scheduler import scheduled_linkintime_company_sync
    res = await scheduled_linkintime_company_sync()
    return res


@router.get(
    "/linkintime/unmatched",
    summary="Get list of Link Intime companies that could not be matched to database IPOs"
)
async def get_unmatched_linkintime_companies():
    """
    Returns the most recent list of Link Intime companies that could not be mapped to any IPO.
    """
    from app.services.scheduler import last_unmatched_linkintime_companies
    return {
        "count": len(last_unmatched_linkintime_companies),
        "unmatched": last_unmatched_linkintime_companies
    }
