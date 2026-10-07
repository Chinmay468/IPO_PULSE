from typing import List
from fastapi import APIRouter, HTTPException, Request, status
from app.schemas.ipo import (
    RegistrarCompanyItem,
    AllotmentQueryRequest,
    AllotmentResultResponse
)
from app.services.registrar_proxy import RegistrarProxyService
from app.auth import limiter

router = APIRouter(prefix="/allotment", tags=["Registrar Allotment Proxy"])


@router.get(
    "/linkintime/companies",
    response_model=List[RegistrarCompanyItem],
    summary="List active companies available on Link Intime portal"
)
async def get_linkintime_companies():
    """
    Returns the list of IPO companies currently available on Link Intime
    for allotment status queries.
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
    Returns standardized status: ALLOTTED, NOT_ALLOTTED, NOT_FOUND, or PENDING.
    Rate limited to 30 requests per minute per IP.
    """
    if not req_body.query_value or len(req_body.query_value.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query_value must be a valid identifier with at least 3 characters"
        )

    result = await RegistrarProxyService.query_allotment(req_body)
    return result
