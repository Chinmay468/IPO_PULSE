import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from app.config import settings
from app.schemas.ipo import (
    RegistrarCompanyItem,
    AllotmentQueryRequest,
    AllotmentResultResponse,
    AllotmentStatus,
    AllotmentQueryType
)

logger = logging.getLogger(__name__)


def mask_identifier(val: Optional[str]) -> str:
    """
    Masks applicant identifiers (PAN, Application No, DP/Client ID) for logging and API outputs.
    Guarantees compliance: raw identifiers are never logged, stored, or returned.
    Example: 'ABCDE1234F' -> 'AB****4F'
    """
    if not val:
        return ""
    s = str(val).strip()
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}****{s[-2:]}"


class RegistrarProxyService:
    """
    Proxy service to query IPO allotment status from Link Intime / MUFG Intime.
    Provides company dropdown fetch and applicant allotment status resolution.
    Strictly follows security policies: masks identifiers and never returns fabricated results.
    """

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://in.mpms.mufg.com/Initial_Offer/public-issues.html",
    }

    @classmethod
    async def get_linkintime_companies(cls) -> List[RegistrarCompanyItem]:
        """
        Fetches the current live list of available companies from Link Intime / MUFG Intime portal.
        Returns an empty list if the registrar endpoint is temporarily unreachable.
        """
        url = f"{settings.LINK_INTIME_API_URL}/GetDetails"
        try:
            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = await client.post(
                    url,
                    json={},
                    headers=cls.DEFAULT_HEADERS
                )
                if response.status_code == 200:
                    data = response.json()
                    xml_str = data.get("d") or ""
                    if xml_str and isinstance(xml_str, str) and ("<Table>" in xml_str or "<table" in xml_str.lower()):
                        root = ET.fromstring(xml_str)
                        results = []
                        seen_ids = set()
                        for table in root.findall(".//Table") or root.findall(".//table"):
                            cid_el = table.find("company_id")
                            cname_el = table.find("companyname")
                            if cid_el is not None and cname_el is not None and cid_el.text and cname_el.text:
                                cid = cid_el.text.strip()
                                cname = cname_el.text.strip()
                                if cid and cid not in seen_ids:
                                    seen_ids.add(cid)
                                    results.append(RegistrarCompanyItem(company_id=cid, company_name=cname))
                        if results:
                            return results
        except Exception as exc:
            logger.warning(f"Could not fetch real-time companies from Link Intime / MUFG API: {exc}")

        # HTML scraping fallback on the main public-issues.html page
        try:
            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
                resp = await client.get(settings.LINK_INTIME_BASE_URL, headers=cls.DEFAULT_HEADERS)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    select_elem = soup.find("select", {"id": re.compile(r"ddlCompany", re.I)})
                    if select_elem:
                        options = select_elem.find_all("option")
                        parsed = []
                        for opt in options:
                            val = opt.get("value", "").strip()
                            txt = opt.get_text().strip()
                            if val and val != "0" and val != "-1" and txt and "Select" not in txt:
                                parsed.append(RegistrarCompanyItem(company_id=val, company_name=txt))
                        if parsed:
                            return parsed
        except Exception as exc:
            logger.warning(f"HTML scraping fallback for Link Intime companies also encountered: {exc}")

        # If live fetch fails, return empty list (no hardcoded fallbacks)
        return []

    @classmethod
    async def query_allotment(cls, request: AllotmentQueryRequest) -> AllotmentResultResponse:
        """
        Executes an allotment query against Link Intime for the requested company and identifier.
        Never logs or returns unmasked identifiers. Never fabricates results.
        """
        clean_val = request.query_value.strip().upper()
        clean_cid = request.company_id.strip()
        masked_val = mask_identifier(clean_val)

        logger.info(f"Checking Link Intime allotment for clientid={clean_cid}, identifier={masked_val}")

        # Resolve company display name & check availability
        companies = await cls.get_linkintime_companies()
        matched_comp = next(
            (c for c in companies if c.company_id == clean_cid or c.company_name.lower() == clean_cid.lower()),
            None
        )

        # If company list is loaded and this company id is not present, report not listed
        if companies and not matched_comp:
            logger.info(f"Company ID {clean_cid} is no longer available on the registrar.")
            return AllotmentResultResponse(
                success=False,
                status=AllotmentStatus.ERROR,
                company_name=f"IPO (Code: {clean_cid})",
                company_id=clean_cid,
                applicant_name=None,
                pan=None,
                application_no=None,
                dp_client_id=None,
                shares_applied=0,
                shares_allotted=0,
                refund_amount=0.0,
                message="No longer available on the registrar"
            )

        company_name = matched_comp.company_name if matched_comp else f"IPO (Code: {clean_cid})"

        # Attempt live MUFG / Link Intime SearchOnPan API with dynamic token
        try:
            chkval_map = {
                AllotmentQueryType.PAN: "1",
                AllotmentQueryType.APPLICATION_NO: "2",
                AllotmentQueryType.DP_CLIENT_ID: "3"
            }
            chkval = chkval_map.get(request.query_type, "1")

            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
                # 1. Generate session token
                token_url = f"{settings.LINK_INTIME_API_URL}/generateToken"
                try:
                    token_res = await client.post(token_url, json={}, headers=cls.DEFAULT_HEADERS)
                    token = token_res.json().get("d", "") if token_res.status_code == 200 else ""
                except Exception as t_err:
                    logger.warning(f"Failed to generate Link Intime session token: {t_err}")
                    return AllotmentResultResponse(
                        success=False,
                        status=AllotmentStatus.ERROR,
                        company_name=company_name,
                        company_id=clean_cid,
                        applicant_name=None,
                        pan=None,
                        application_no=None,
                        dp_client_id=None,
                        shares_applied=0,
                        shares_allotted=0,
                        refund_amount=0.0,
                        message="Registrar unavailable"
                    )

                # 2. Execute search
                search_url = f"{settings.LINK_INTIME_API_URL}/SearchOnPan"
                payload = {
                    "clientid": clean_cid,
                    "PAN": clean_val,
                    "IFSC": "",
                    "CHKVAL": chkval,
                    "token": token
                }

                res = await client.post(search_url, json=payload, headers=cls.DEFAULT_HEADERS)
                if res.status_code == 200:
                    resp_data = res.json()
                    xml_str = resp_data.get("d") or ""
                    if xml_str and isinstance(xml_str, str) and "<Table>" in xml_str:
                        root = ET.fromstring(xml_str)
                        tables = root.findall(".//Table")
                        if tables:
                            first = tables[0]
                            allot_el = first.find("ALLOT")
                            appl_el = first.find("APPL")
                            name_el = first.find("NAME1")
                            if name_el is None:
                                name_el = first.find("name")
                            rfnd_el = first.find("RFNDAMT")
                            sec_el = first.find("SEC")

                            shares_allotted = int(allot_el.text.strip()) if (allot_el is not None and allot_el.text) else 0
                            shares_applied = int(appl_el.text.strip()) if (appl_el is not None and appl_el.text) else 0
                            applicant = name_el.text.strip() if (name_el is not None and name_el.text) else "Registered Investor"
                            refund_amt = float(rfnd_el.text.strip()) if (rfnd_el is not None and rfnd_el.text) else 0.0
                            if sec_el is not None and sec_el.text:
                                company_name = sec_el.text.strip()

                            status = AllotmentStatus.ALLOTTED if shares_allotted > 0 else AllotmentStatus.NOT_ALLOTTED
                            msg = f"Congratulations! {shares_allotted} shares allotted." if shares_allotted > 0 else f"Application processed. No shares allotted for {company_name}."

                            return AllotmentResultResponse(
                                success=True,
                                status=status,
                                company_name=company_name,
                                company_id=clean_cid,
                                applicant_name=applicant,
                                pan=masked_val if request.query_type == AllotmentQueryType.PAN else None,
                                application_no=masked_val if request.query_type == AllotmentQueryType.APPLICATION_NO else None,
                                dp_client_id=masked_val if request.query_type == AllotmentQueryType.DP_CLIENT_ID else None,
                                shares_applied=shares_applied,
                                shares_allotted=shares_allotted,
                                refund_amount=refund_amt,
                                message=msg
                            )
                    elif xml_str and "<NewDataSet" in xml_str:
                        # Empty dataset -> Record not found
                        return AllotmentResultResponse(
                            success=True,
                            status=AllotmentStatus.NOT_FOUND,
                            company_name=company_name,
                            company_id=clean_cid,
                            applicant_name="N/A",
                            pan=masked_val if request.query_type == AllotmentQueryType.PAN else None,
                            application_no=masked_val if request.query_type == AllotmentQueryType.APPLICATION_NO else None,
                            dp_client_id=masked_val if request.query_type == AllotmentQueryType.DP_CLIENT_ID else None,
                            shares_applied=0,
                            shares_allotted=0,
                            message=f"No application record found for {masked_val} under {company_name}. Please verify your details."
                        )
                    else:
                        logger.warning(f"Unexpected response format from Link Intime for cid={clean_cid}: {xml_str[:100]}")
                        return AllotmentResultResponse(
                            success=False,
                            status=AllotmentStatus.ERROR,
                            company_name=company_name,
                            company_id=clean_cid,
                            applicant_name=None,
                            pan=None,
                            application_no=None,
                            dp_client_id=None,
                            shares_applied=0,
                            shares_allotted=0,
                            refund_amount=0.0,
                            message="No longer available on the registrar"
                        )
                elif res.status_code in [404, 400]:
                    return AllotmentResultResponse(
                        success=False,
                        status=AllotmentStatus.ERROR,
                        company_name=company_name,
                        company_id=clean_cid,
                        applicant_name=None,
                        pan=None,
                        application_no=None,
                        dp_client_id=None,
                        shares_applied=0,
                        shares_allotted=0,
                        refund_amount=0.0,
                        message="No longer available on the registrar"
                    )
                else:
                    return AllotmentResultResponse(
                        success=False,
                        status=AllotmentStatus.ERROR,
                        company_name=company_name,
                        company_id=clean_cid,
                        applicant_name=None,
                        pan=None,
                        application_no=None,
                        dp_client_id=None,
                        shares_applied=0,
                        shares_allotted=0,
                        refund_amount=0.0,
                        message="Registrar unavailable"
                    )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as net_err:
            logger.warning(f"Network error communicating with Link Intime: {net_err}")
            return AllotmentResultResponse(
                success=False,
                status=AllotmentStatus.ERROR,
                company_name=company_name,
                company_id=clean_cid,
                applicant_name=None,
                pan=None,
                application_no=None,
                dp_client_id=None,
                shares_applied=0,
                shares_allotted=0,
                refund_amount=0.0,
                message="Registrar unavailable"
            )
        except Exception as exc:
            logger.warning(f"Live Link Intime query failed for cid={clean_cid}, id={masked_val}: {exc}")
            return AllotmentResultResponse(
                success=False,
                status=AllotmentStatus.ERROR,
                company_name=company_name,
                company_id=clean_cid,
                applicant_name=None,
                pan=None,
                application_no=None,
                dp_client_id=None,
                shares_applied=0,
                shares_allotted=0,
                refund_amount=0.0,
                message="Registrar unavailable"
            )
