import logging
import re
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.ipo import (
    IPO,
    IPOSubscription,
    IPOGmp,
    IPOScore,
    IPOType,
    IPOStatus
)
from app.services.scoring_service import ScoringService

logger = logging.getLogger(__name__)


class ScraperService:
    """
    Market scraper for IPO master data, subscription status, and Grey Market Premium (GMP).
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    @staticmethod
    def _clean_number(val: Optional[str]) -> Optional[float]:
        if not val:
            return None
        cleaned = re.sub(r"[^\d.-]", "", val)
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    async def scrape_gmp_feed(cls) -> List[Dict[str, Any]]:
        """
        Attempts to scrape current GMP updates from public market sources.
        Returns a list of structured GMP records.
        """
        results: List[Dict[str, Any]] = []
        url = "https://www.investorgain.com/report/live-ipo-gmp/331/"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(url, headers=cls.HEADERS)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    table = soup.find("table")
                    if table:
                        rows = table.find_all("tr")
                        for row in rows[1:]:
                            cols = [td.get_text().strip() for td in row.find_all(["td", "th"])]
                            if len(cols) >= 4:
                                name = cols[0]
                                gmp_raw = cols[2] if len(cols) > 2 else ""
                                pct_raw = cols[3] if len(cols) > 3 else ""
                                gmp_val = cls._clean_number(gmp_raw)
                                pct_val = cls._clean_number(pct_raw)
                                if name and (gmp_val is not None or pct_val is not None):
                                    results.append({
                                        "company_name": name,
                                        "gmp_amount": gmp_val,
                                        "gmp_percentage": pct_val,
                                        "source": "investorgain"
                                    })
        except Exception as exc:
            logger.info(f"Live GMP web scrape encountered network/html variance: {exc}")

        return results

    @classmethod
    async def scrape_subscription_feed(cls) -> List[Dict[str, Any]]:
        """
        Attempts to scrape subscription multiples from public market sources.
        """
        results: List[Dict[str, Any]] = []
        url = "https://www.chittorgarh.com/report/ipo-subscription-status-live-bidding-data-bse-nse/21/"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(url, headers=cls.HEADERS)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    table = soup.find("table")
                    if table:
                        rows = table.find_all("tr")
                        for row in rows[1:]:
                            cols = [td.get_text().strip() for td in row.find_all(["td", "th"])]
                            if len(cols) >= 5:
                                name = cols[0]
                                qib = cls._clean_number(cols[1])
                                nii = cls._clean_number(cols[2])
                                retail = cls._clean_number(cols[3])
                                total = cls._clean_number(cols[4])
                                if name:
                                    results.append({
                                        "company_name": name,
                                        "qib_multiple": qib,
                                        "nii_multiple": nii,
                                        "retail_multiple": retail,
                                        "total_multiple": total
                                    })
        except Exception as exc:
            logger.info(f"Live subscription web scrape encountered: {exc}")

        return results

    @classmethod
    async def seed_market_data(cls, session: AsyncSession) -> int:
        """
        Seeds sample IPO master records, subscription data, and GMP records,
        then computes their initial scores.
        """
        today = date.today()
        seed_ipos = [
            {
                "symbol": "VISHALNIR",
                "company_name": "Vishal Nirmiti Ltd",
                "ipo_type": IPOType.MAINBOARD,
                "status": IPOStatus.LIVE,
                "price_band_low": 140.0,
                "price_band_high": 148.0,
                "issue_price": 148.0,
                "lot_size": 100,
                "issue_size_crores": 320.0,
                "fresh_issue_crores": 250.0,
                "ofs_crores": 70.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1012",
                "pe_ratio": 28.0,
                "industry_pe": 32.0,
                "ronw": 14.5,
                "eps": 5.28,
                "sector": "Precast Concrete & Infrastructure",
                "revenue_growth_yoy": 14.2,
                "pat_growth_yoy": 18.5,
                "debt_to_equity": 0.68,
                "pat_margin_pct": 7.8,
                "promoter_holding_pre": 88.0,
                "promoter_holding_post": 65.5,
                "gmp": {"gmp_amount": 6.0, "gmp_percentage": 4.05, "source": "investorgain"},
                "sub": {"qib_multiple": 0.0, "nii_multiple": 0.02, "retail_multiple": 0.05, "total_multiple": 0.03}
            },
            {
                "symbol": "NITYASGEMS",
                "company_name": "Nityas Gems & Jewellery Ltd",
                "ipo_type": IPOType.MAINBOARD,
                "status": IPOStatus.LIVE,
                "price_band_low": 210.0,
                "price_band_high": 225.0,
                "issue_price": 225.0,
                "lot_size": 65,
                "issue_size_crores": 410.0,
                "fresh_issue_crores": 300.0,
                "ofs_crores": 110.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "KFin Technologies Limited",
                "registrar_code": "NITYAS",
                "pe_ratio": 24.0,
                "industry_pe": 30.0,
                "ronw": 16.2,
                "eps": 9.38,
                "sector": "Gems & Jewellery Retail",
                "revenue_growth_yoy": 22.4,
                "pat_growth_yoy": 28.1,
                "debt_to_equity": 0.52,
                "pat_margin_pct": 9.4,
                "promoter_holding_pre": 91.2,
                "promoter_holding_post": 66.8,
                "gmp": {"gmp_amount": 18.0, "gmp_percentage": 8.0, "source": "chittorgarh"},
                "sub": {"qib_multiple": 0.05, "nii_multiple": 0.12, "retail_multiple": 0.22, "total_multiple": 0.14}
            },
            {
                "symbol": "GREENASIA",
                "company_name": "Green Asia Impex Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 95.0,
                "price_band_high": 100.0,
                "issue_price": 100.0,
                "lot_size": 1200,
                "issue_size_crores": 24.0,
                "fresh_issue_crores": 24.0,
                "ofs_crores": 0.0,
                "open_date": today - timedelta(days=1),
                "close_date": date(2026, 10, 1),
                "allotment_date": date(2026, 10, 3),
                "listing_date": date(2026, 10, 6),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1013",
                "pe_ratio": 17.5,
                "industry_pe": 25.0,
                "ronw": 19.8,
                "eps": 5.71,
                "sector": "Agro Commodities & Export",
                "revenue_growth_yoy": 16.8,
                "pat_growth_yoy": 19.4,
                "debt_to_equity": 0.38,
                "pat_margin_pct": 6.5,
                "promoter_holding_pre": 100.0,
                "promoter_holding_post": 73.5,
                "gmp": {"gmp_amount": 12.0, "gmp_percentage": 12.0, "source": "investorgain"},
                "sub": {"qib_multiple": 0.20, "nii_multiple": 0.45, "retail_multiple": 0.78, "total_multiple": 0.53}
            },
            {
                "symbol": "BLACKOPAL",
                "company_name": "Black Opal Consultants Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 75.0,
                "price_band_high": 80.0,
                "issue_price": 80.0,
                "lot_size": 1600,
                "issue_size_crores": 18.5,
                "fresh_issue_crores": 18.5,
                "ofs_crores": 0.0,
                "open_date": today - timedelta(days=1),
                "close_date": date(2026, 10, 1),
                "allotment_date": date(2026, 10, 3),
                "listing_date": date(2026, 10, 6),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1014",
                "pe_ratio": 16.0,
                "industry_pe": 28.0,
                "ronw": 22.4,
                "eps": 5.0,
                "sector": "Management Consulting & Analytics",
                "revenue_growth_yoy": 31.2,
                "pat_growth_yoy": 38.6,
                "debt_to_equity": 0.12,
                "pat_margin_pct": 16.8,
                "promoter_holding_pre": 86.5,
                "promoter_holding_post": 63.0,
                "gmp": {"gmp_amount": 16.0, "gmp_percentage": 20.0, "source": "investorgain"},
                "sub": {"qib_multiple": 0.90, "nii_multiple": 1.45, "retail_multiple": 1.35, "total_multiple": 1.24}
            },
            {
                "symbol": "VANSELECTRO",
                "company_name": "Vans Electroengineerings Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 110.0,
                "price_band_high": 118.0,
                "issue_price": 118.0,
                "lot_size": 1200,
                "issue_size_crores": 35.0,
                "fresh_issue_crores": 35.0,
                "ofs_crores": 0.0,
                "open_date": today - timedelta(days=1),
                "close_date": date(2026, 10, 1),
                "allotment_date": date(2026, 10, 3),
                "listing_date": date(2026, 10, 6),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1015",
                "pe_ratio": 14.8,
                "industry_pe": 35.0,
                "ronw": 31.5,
                "eps": 7.97,
                "sector": "Electrical Engineering & Switchgears",
                "revenue_growth_yoy": 48.5,
                "pat_growth_yoy": 64.2,
                "debt_to_equity": 0.25,
                "pat_margin_pct": 15.4,
                "promoter_holding_pre": 82.0,
                "promoter_holding_post": 60.0,
                "gmp": {"gmp_amount": 75.0, "gmp_percentage": 63.56, "source": "investorgain"},
                "sub": {"qib_multiple": 42.10, "nii_multiple": 98.40, "retail_multiple": 58.20, "total_multiple": 64.58}
            },
            {
                "symbol": "PAPADMALJI",
                "company_name": "Papadmalji Agro Foods Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 65.0,
                "price_band_high": 70.0,
                "issue_price": 70.0,
                "lot_size": 2000,
                "issue_size_crores": 16.8,
                "fresh_issue_crores": 16.8,
                "ofs_crores": 0.0,
                "open_date": today - timedelta(days=1),
                "close_date": date(2026, 10, 1),
                "allotment_date": date(2026, 10, 3),
                "listing_date": date(2026, 10, 6),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1016",
                "pe_ratio": 15.2,
                "industry_pe": 24.0,
                "ronw": 18.7,
                "eps": 4.61,
                "sector": "FMCG & Food Processing",
                "revenue_growth_yoy": 11.5,
                "pat_growth_yoy": 14.0,
                "debt_to_equity": 0.85,
                "pat_margin_pct": 5.2,
                "promoter_holding_pre": 89.0,
                "promoter_holding_post": 64.0,
                "gmp": {"gmp_amount": 15.0, "gmp_percentage": 21.43, "source": "investorgain"},
                "sub": {"qib_multiple": 1.10, "nii_multiple": 2.15, "retail_multiple": 1.82, "total_multiple": 1.69}
            },
            {
                "symbol": "DOVESOFT",
                "company_name": "Dove Soft Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 145.0,
                "price_band_high": 155.0,
                "issue_price": 155.0,
                "lot_size": 900,
                "issue_size_crores": 28.0,
                "fresh_issue_crores": 28.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1011",
                "pe_ratio": 21.5,
                "industry_pe": 36.0,
                "ronw": 23.1,
                "eps": 7.21,
                "sector": "Enterprise Software & Cloud Messaging",
                "revenue_growth_yoy": 34.0,
                "pat_growth_yoy": 41.5,
                "debt_to_equity": 0.08,
                "pat_margin_pct": 19.2,
                "promoter_holding_pre": 78.0,
                "promoter_holding_post": 58.0,
                "gmp": {"gmp_amount": 38.0, "gmp_percentage": 24.52, "source": "investorgain"},
                "sub": {"qib_multiple": 0.40, "nii_multiple": 0.95, "retail_multiple": 1.15, "total_multiple": 0.85}
            },
            {
                "symbol": "EVERESTIMS",
                "company_name": "EverestIMS Technologies Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 115.0,
                "price_band_high": 122.0,
                "issue_price": 122.0,
                "lot_size": 1000,
                "issue_size_crores": 42.5,
                "fresh_issue_crores": 42.5,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1003",
                "pe_ratio": 19.2,
                "industry_pe": 32.0,
                "ronw": 24.5,
                "eps": 6.35,
                "gmp": {"gmp_amount": 28.0, "gmp_percentage": 22.95, "source": "investorgain"},
                "sub": {"qib_multiple": 0.0, "nii_multiple": 0.10, "retail_multiple": 0.22, "total_multiple": 0.13}
            },
            {
                "symbol": "OMARAVENT",
                "company_name": "Omara Ventures India Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 80.0,
                "price_band_high": 85.0,
                "issue_price": 85.0,
                "lot_size": 1600,
                "issue_size_crores": 19.5,
                "fresh_issue_crores": 19.5,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1017",
                "pe_ratio": 18.0,
                "industry_pe": 26.0,
                "ronw": 16.5,
                "eps": 4.72,
                "gmp": {"gmp_amount": 10.0, "gmp_percentage": 11.76, "source": "chittorgarh"},
                "sub": {"qib_multiple": 0.15, "nii_multiple": 0.40, "retail_multiple": 0.82, "total_multiple": 0.53}
            },
            {
                "symbol": "EVENTIONS",
                "company_name": "Eventions Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 92.0,
                "price_band_high": 98.0,
                "issue_price": 98.0,
                "lot_size": 1200,
                "issue_size_crores": 22.0,
                "fresh_issue_crores": 22.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1018",
                "pe_ratio": 17.0,
                "industry_pe": 30.0,
                "ronw": 20.8,
                "eps": 5.76,
                "gmp": {"gmp_amount": 22.0, "gmp_percentage": 22.45, "source": "investorgain"},
                "sub": {"qib_multiple": 0.80, "nii_multiple": 1.25, "retail_multiple": 1.30, "total_multiple": 1.12}
            },
            {
                "symbol": "SHREETNB",
                "company_name": "Shree TNB Polymers Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 70.0,
                "price_band_high": 75.0,
                "issue_price": 75.0,
                "lot_size": 1600,
                "issue_size_crores": 15.0,
                "fresh_issue_crores": 15.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1019",
                "pe_ratio": 16.5,
                "industry_pe": 25.0,
                "ronw": 17.2,
                "eps": 4.55,
                "gmp": {"gmp_amount": 9.0, "gmp_percentage": 12.0, "source": "investorgain"},
                "sub": {"qib_multiple": 0.25, "nii_multiple": 0.60, "retail_multiple": 0.95, "total_multiple": 0.66}
            },
            {
                "symbol": "SJPULTRA",
                "company_name": "SJP Ultrasonics Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 105.0,
                "price_band_high": 112.0,
                "issue_price": 112.0,
                "lot_size": 1200,
                "issue_size_crores": 26.5,
                "fresh_issue_crores": 26.5,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1020",
                "pe_ratio": 18.5,
                "industry_pe": 28.0,
                "ronw": 18.0,
                "eps": 6.05,
                "gmp": {"gmp_amount": 14.0, "gmp_percentage": 12.50, "source": "chittorgarh"},
                "sub": {"qib_multiple": 0.10, "nii_multiple": 0.35, "retail_multiple": 0.68, "total_multiple": 0.42}
            },
            {
                "symbol": "SOLLFEGE",
                "company_name": "Sollfege Smart Electronics Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 125.0,
                "price_band_high": 132.0,
                "issue_price": 132.0,
                "lot_size": 1000,
                "issue_size_crores": 31.0,
                "fresh_issue_crores": 31.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 5),
                "allotment_date": date(2026, 10, 8),
                "listing_date": date(2026, 10, 12),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1021",
                "pe_ratio": 19.8,
                "industry_pe": 34.0,
                "ronw": 25.2,
                "eps": 6.67,
                "gmp": {"gmp_amount": 32.0, "gmp_percentage": 24.24, "source": "investorgain"},
                "sub": {"qib_multiple": 0.70, "nii_multiple": 1.15, "retail_multiple": 1.32, "total_multiple": 1.06}
            },
            {
                "symbol": "ACMEINDIA",
                "company_name": "Acme India Industries Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 88.0,
                "price_band_high": 94.0,
                "issue_price": 94.0,
                "lot_size": 1200,
                "issue_size_crores": 25.0,
                "fresh_issue_crores": 25.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 6),
                "allotment_date": date(2026, 10, 9),
                "listing_date": date(2026, 10, 13),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1022",
                "pe_ratio": 16.8,
                "industry_pe": 27.0,
                "ronw": 21.5,
                "eps": 5.60,
                "gmp": {"gmp_amount": 26.0, "gmp_percentage": 27.66, "source": "investorgain"},
                "sub": {"qib_multiple": 1.20, "nii_multiple": 2.10, "retail_multiple": 1.95, "total_multiple": 1.76}
            },
            {
                "symbol": "PARAMSNTX",
                "company_name": "Paramount Syntex Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 250.0,
                "price_band_high": 265.0,
                "issue_price": 265.0,
                "lot_size": 500,
                "issue_size_crores": 45.0,
                "fresh_issue_crores": 45.0,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 6),
                "allotment_date": date(2026, 10, 9),
                "listing_date": date(2026, 10, 13),
                "registrar_name": "KFin Technologies Limited",
                "registrar_code": "PARAMSNTX",
                "pe_ratio": 22.0,
                "industry_pe": 30.0,
                "ronw": 17.5,
                "eps": 12.05,
                "gmp": {"gmp_amount": 45.0, "gmp_percentage": 16.98, "source": "chittorgarh"},
                "sub": {"qib_multiple": 0.85, "nii_multiple": 1.55, "retail_multiple": 1.45, "total_multiple": 1.30}
            },
            {
                "symbol": "TNASOL",
                "company_name": "TNA Solutions Ltd",
                "ipo_type": IPOType.SME,
                "status": IPOStatus.LIVE,
                "price_band_low": 60.0,
                "price_band_high": 64.0,
                "issue_price": 64.0,
                "lot_size": 2000,
                "issue_size_crores": 14.2,
                "fresh_issue_crores": 14.2,
                "ofs_crores": 0.0,
                "open_date": today,
                "close_date": date(2026, 10, 6),
                "allotment_date": date(2026, 10, 9),
                "listing_date": date(2026, 10, 13),
                "registrar_name": "Link Intime India Private Ltd",
                "registrar_code": "1023",
                "pe_ratio": 17.2,
                "industry_pe": 24.0,
                "ronw": 14.8,
                "eps": 3.72,
                "gmp": {"gmp_amount": 5.0, "gmp_percentage": 7.81, "source": "investorgain"},
                "sub": {"qib_multiple": 0.05, "nii_multiple": 0.20, "retail_multiple": 0.42, "total_multiple": 0.25}
            }
        ]

        count = 0
        for item in seed_ipos:
            stmt = select(IPO).where(IPO.symbol == item["symbol"])
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            gmp_info = item.pop("gmp")
            sub_info = item.pop("sub")

            if not existing:
                ipo_obj = IPO(**item)
                session.add(ipo_obj)
                await session.flush()
                count += 1
            else:
                ipo_obj = existing
                for k, v in item.items():
                    setattr(ipo_obj, k, v)
                await session.flush()

            # Seed or update GMP
            latest_gmp: Optional[IPOGmp] = None
            if gmp_info:
                gmp_record = IPOGmp(
                    ipo_id=ipo_obj.id,
                    gmp_amount=gmp_info["gmp_amount"],
                    gmp_percentage=gmp_info["gmp_percentage"],
                    source=gmp_info["source"]
                )
                session.add(gmp_record)
                await session.flush()
                latest_gmp = gmp_record

            # Seed or update Subscription
            latest_sub: Optional[IPOSubscription] = None
            if sub_info:
                sub_record = IPOSubscription(
                    ipo_id=ipo_obj.id,
                    **sub_info
                )
                session.add(sub_record)
                await session.flush()
                latest_sub = sub_record

            # Compute and persist composite score
            score_data = ScoringService.calculate_score(
                ipo=ipo_obj,
                latest_subscription=latest_sub,
                latest_gmp=latest_gmp
            )

            score_stmt = select(IPOScore).where(IPOScore.ipo_id == ipo_obj.id)
            score_res = await session.execute(score_stmt)
            existing_score = score_res.scalar_one_or_none()

            if existing_score:
                existing_score.composite_score = score_data["composite_score"]
                existing_score.recommendation = score_data["recommendation"]
                existing_score.gmp_score = score_data["gmp_score"]
                existing_score.subscription_score = score_data["subscription_score"]
                existing_score.valuation_score = score_data["valuation_score"]
                existing_score.structure_score = score_data["structure_score"]
                existing_score.rationale = score_data["rationale"]
            else:
                new_score = IPOScore(
                    ipo_id=ipo_obj.id,
                    composite_score=score_data["composite_score"],
                    recommendation=score_data["recommendation"],
                    gmp_score=score_data["gmp_score"],
                    subscription_score=score_data["subscription_score"],
                    valuation_score=score_data["valuation_score"],
                    structure_score=score_data["structure_score"],
                    rationale=score_data["rationale"]
                )
                session.add(new_score)

        await session.commit()
        return count

    @classmethod
    async def sync_market_data(cls, session: AsyncSession) -> Dict[str, Any]:
        """
        Runs complete sync: scrapes live feeds, updates DB records, and recalculates composite scores.
        """
        logger.info("Starting market data sync...")
        gmp_records = await cls.scrape_gmp_feed()
        sub_records = await cls.scrape_subscription_feed()

        # Query all active or upcoming IPOs
        stmt = select(IPO).where(IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]))
        result = await session.execute(stmt)
        active_ipos = result.scalars().all()

        now_sync = datetime.now(timezone.utc)
        updated_count = 0
        for ipo in active_ipos:
            ipo.updated_at = now_sync

            # Match GMP
            matched_gmp = next(
                (g for g in gmp_records if ipo.symbol.lower() in g["company_name"].lower() or g["company_name"].lower() in ipo.company_name.lower()),
                None
            )
            latest_gmp_obj: Optional[IPOGmp] = None
            if matched_gmp:
                gmp_amt = matched_gmp.get("gmp_amount")
                gmp_pct = matched_gmp.get("gmp_percentage")
                base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low or 0.0
                if gmp_amt is None and gmp_pct is not None and base_price > 0:
                    gmp_amt = round((gmp_pct / 100.0) * base_price, 2)
                elif gmp_amt is None:
                    gmp_amt = 0.0

                if gmp_pct is None and gmp_amt is not None and base_price > 0:
                    gmp_pct = round((gmp_amt / base_price) * 100.0, 2)
                elif gmp_pct is None:
                    gmp_pct = 0.0

                latest_gmp_obj = IPOGmp(
                    ipo_id=ipo.id,
                    gmp_amount=gmp_amt,
                    gmp_percentage=gmp_pct,
                    source=matched_gmp.get("source", "market"),
                    recorded_at=now_sync
                )
                session.add(latest_gmp_obj)

            # Match Subscription
            matched_sub = next(
                (s for s in sub_records if ipo.symbol.lower() in s["company_name"].lower() or s["company_name"].lower() in ipo.company_name.lower()),
                None
            )
            latest_sub_obj: Optional[IPOSubscription] = None
            if matched_sub:
                tot_mult = matched_sub.get("total_multiple")
                if tot_mult is None:
                    tot_mult = 0.0
                latest_sub_obj = IPOSubscription(
                    ipo_id=ipo.id,
                    qib_multiple=matched_sub["qib_multiple"],
                    nii_multiple=matched_sub["nii_multiple"],
                    retail_multiple=matched_sub["retail_multiple"],
                    total_multiple=tot_mult,
                    recorded_at=now_sync
                )
                session.add(latest_sub_obj)

            await session.flush()

            # Retrieve latest records if not updated in this cycle
            if not latest_gmp_obj:
                gmp_stmt = select(IPOGmp).where(IPOGmp.ipo_id == ipo.id).order_by(IPOGmp.recorded_at.desc()).limit(1)
                latest_gmp_obj = (await session.execute(gmp_stmt)).scalar_one_or_none()

            if not latest_sub_obj:
                sub_stmt = select(IPOSubscription).where(IPOSubscription.ipo_id == ipo.id).order_by(IPOSubscription.recorded_at.desc()).limit(1)
                latest_sub_obj = (await session.execute(sub_stmt)).scalar_one_or_none()

            # Recalculate score
            score_data = ScoringService.calculate_score(
                ipo=ipo,
                latest_subscription=latest_sub_obj,
                latest_gmp=latest_gmp_obj
            )

            score_stmt = select(IPOScore).where(IPOScore.ipo_id == ipo.id)
            score_obj = (await session.execute(score_stmt)).scalar_one_or_none()
            if score_obj:
                score_obj.composite_score = score_data["composite_score"]
                score_obj.recommendation = score_data["recommendation"]
                score_obj.gmp_score = score_data["gmp_score"]
                score_obj.subscription_score = score_data["subscription_score"]
                score_obj.valuation_score = score_data["valuation_score"]
                score_obj.structure_score = score_data["structure_score"]
                score_obj.rationale = score_data["rationale"]
                score_obj.calculated_at = now_sync
            else:
                session.add(IPOScore(ipo_id=ipo.id, calculated_at=now_sync, **score_data))

            updated_count += 1

        await session.commit()
        return {
            "status": "success",
            "gmp_scraped": len(gmp_records),
            "subscription_scraped": len(sub_records),
            "ipos_updated": updated_count,
            "timestamp": datetime.now().isoformat()
        }
