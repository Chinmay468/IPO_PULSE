import logging
import os
import re
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.models.ipo import (
    IPO,
    IPOSubscription,
    IPOGmp,
    IPOScore,
    IPOType,
    IPOStatus
)
from app.services.scoring_service import ScoringService
from app.services.consensus_gmp import ConsensusGmpService
from app.services.ipowatch_scraper import IPOWatchScraper
from app.services.gmp_matcher import match_gmp_records_to_ipos, normalize_for_gmp_match
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


class ScraperService:
    """
    Market scraper for IPO master data, subscription status, and Grey Market Premium (GMP).
    """

    _gmp_alert_active: bool = False
    _gmp_quality_status: Dict[str, Any] = {"alert_active": False, "message": ""}

    @classmethod
    def get_gmp_quality_status(cls) -> Dict[str, Any]:
        return cls._gmp_quality_status

    @classmethod
    def evaluate_gmp_quality(
        cls,
        ig_count: int,
        iw_count: int,
        live_ipos_count: int,
        live_ipos_with_fresh_gmp: int
    ) -> Dict[str, Any]:
        """
        Determines whether the 'GMP source unavailable, scores are partial' banner
        should be active: strictly when all GMP sources fail OR fewer than 50% of live IPOs have fresh GMP.
        """
        all_sources_failed = (ig_count == 0 and iw_count == 0)
        low_coverage = (live_ipos_count > 0 and (live_ipos_with_fresh_gmp / live_ipos_count) < 0.50)

        if all_sources_failed or low_coverage:
            reason = "All GMP sources failed" if all_sources_failed else "Fewer than 50% of live IPOs have fresh GMP data"
            return {
                "alert_active": True,
                "message": "GMP source unavailable, scores are partial.",
                "reason": reason
            }
        return {
            "alert_active": False,
            "message": "",
            "reason": "OK"
        }

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
    def parse_investorgain_table(cls, html: str) -> List[Dict[str, Any]]:
        """
        Parses InvestorGain GMP table mapping columns by header text dynamically:
        - Required headers: Name/Company and GMP.
        - Raises ValueError and logs alert if required headers are missing.
        - Alerts if >50% of parsed rows have empty GMP (once per incident).
        - Never writes a default 0 if GMP is '--' or missing.
        """
        results: List[Dict[str, Any]] = []
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return results

        rows = table.find_all("tr")
        if not rows:
            return results

        # 1. Map columns by header text
        header_row = rows[0]
        header_cells = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

        name_idx: Optional[int] = None
        gmp_idx: Optional[int] = None
        sub_idx: Optional[int] = None
        price_idx: Optional[int] = None
        open_idx: Optional[int] = None
        close_idx: Optional[int] = None

        for idx, h in enumerate(header_cells):
            if name_idx is None and ("name" in h or "company" in h):
                name_idx = idx
            elif gmp_idx is None and "gmp" in h:
                gmp_idx = idx
            elif sub_idx is None and "sub" in h:
                sub_idx = idx
            elif price_idx is None and "price" in h:
                price_idx = idx
            elif open_idx is None and "open" in h:
                open_idx = idx
            elif close_idx is None and "close" in h:
                close_idx = idx

        # Required headers check
        if name_idx is None or gmp_idx is None:
            err_msg = f"InvestorGain required header missing (Name or GMP). Found: {header_cells}"
            logger.error(f"[InvestorGain] {err_msg}")
            raise ValueError(err_msg)

        total_rows = 0
        empty_gmp_rows = 0

        for row in rows[1:]:
            cols = [td.get_text().strip() for td in row.find_all(["td", "th"])]
            if len(cols) > max(name_idx, gmp_idx):
                name = cols[name_idx]
                if not name or name.lower() in ("name", "company"):
                    continue

                total_rows += 1
                gmp_col = cols[gmp_idx] if gmp_idx is not None and gmp_idx < len(cols) else ""
                sub_col = cols[sub_idx] if sub_idx is not None and sub_idx < len(cols) else ""
                price_col = cols[price_idx] if price_idx is not None and price_idx < len(cols) else ""
                open_col = cols[open_idx] if open_idx is not None and open_idx < len(cols) else ""
                close_col = cols[close_idx] if close_idx is not None and close_idx < len(cols) else ""

                # Parse GMP and Percentage: e.g. '₹88(12.70%)83 ↓ / 95 ↑'
                m_gmp = re.search(r"₹\s*([0-9,.]+)\s*\(([0-9,.]+)%\)", gmp_col)
                gmp_amt = float(m_gmp.group(1).replace(",", "")) if m_gmp else None
                gmp_pct = float(m_gmp.group(2).replace(",", "")) if m_gmp else None

                if gmp_amt is None:
                    empty_gmp_rows += 1

                # Price band / issue price
                price_nums = [float(p.replace(",", "")) for p in re.findall(r"\b[0-9,.]+\b", price_col) if p.replace(",", "").replace(".", "").isdigit()]
                price = max(price_nums) if price_nums else None

                # Sub total multiple
                sub_val = None
                m_sub = re.search(r"([0-9,.]+)\s*x", sub_col)
                if m_sub:
                    try:
                        sub_val = float(m_sub.group(1).replace(",", ""))
                    except ValueError:
                        pass

                # If '--' in gmp_col and no numeric match, keep gmp_amt None (never write default 0)
                if gmp_amt is not None:
                    # Strip any appended GMP note from date cells
                    m_open = re.search(r"(\d{1,2}\s*[-/]\s*[A-Za-z]{3})", open_col)
                    m_close = re.search(r"(\d{1,2}\s*[-/]\s*[A-Za-z]{3})", close_col)
                    clean_open = m_open.group(1) if m_open else open_col
                    clean_close = m_close.group(1) if m_close else close_col
                    date_span = f"{clean_open} - {clean_close}".strip(" -")

                    results.append({
                        "company_name": name,
                        "gmp_amount": gmp_amt,
                        "gmp_percentage": gmp_pct if gmp_pct is not None else 0.0,
                        "price": price,
                        "date_str": date_span,
                        "subscription_total": sub_val,
                        "source": "investorgain"
                    })

        # Quality check: >50% empty GMP
        if total_rows > 0 and (empty_gmp_rows / total_rows) > 0.50:
            cls._gmp_quality_status = {
                "alert_active": True,
                "message": "More than 50% of parsed InvestorGain rows have empty GMP."
            }
            logger.warning(f"[InvestorGain Quality Alert] {empty_gmp_rows}/{total_rows} rows have empty GMP.")

        return results

    @classmethod
    async def scrape_gmp_feed(cls) -> List[Dict[str, Any]]:
        """
        Attempts to scrape current GMP updates from public market sources (InvestorGain).
        Returns a list of structured GMP records.
        """
        url = "https://www.investorgain.com/report/live-ipo-gmp/331/"

        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                res = await client.get(url, headers=cls.HEADERS)
                if res.status_code == 200:
                    return cls.parse_investorgain_table(res.text)
                else:
                    logger.warning(f"InvestorGain returned HTTP {res.status_code}")
        except Exception as exc:
            logger.info(f"Live GMP web scrape encountered network/html variance: {exc}")

        return []

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
        Only allowed when ALLOW_SEED=1 environment variable is explicitly set.
        """
        if os.getenv("ALLOW_SEED") != "1":
            raise PermissionError(
                "Market data seeding is prohibited in production. "
                "Set ALLOW_SEED=1 environment variable to permit seeding."
            )

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
                "status": IPOStatus.CLOSED,
                "price_band_low": 210.0,
                "price_band_high": 225.0,
                "issue_price": 225.0,
                "lot_size": 65,
                "issue_size_crores": 410.0,
                "fresh_issue_crores": 300.0,
                "ofs_crores": 110.0,
                "open_date": date(2026, 10, 1),
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
                "sub": {"qib_multiple": 24.50, "nii_multiple": 14.80, "retail_multiple": 16.20, "total_multiple": 18.52}
            },
            {
                "symbol": "NTPCGREEN",
                "company_name": "NTPC Green Energy Ltd",
                "ipo_type": IPOType.MAINBOARD,
                "status": IPOStatus.UPCOMING,
                "price_band_low": 102.0,
                "price_band_high": 108.0,
                "issue_price": 108.0,
                "lot_size": 138,
                "issue_size_crores": 10000.0,
                "fresh_issue_crores": 10000.0,
                "ofs_crores": 0.0,
                "open_date": today + timedelta(days=11),
                "close_date": today + timedelta(days=13),
                "allotment_date": today + timedelta(days=16),
                "listing_date": today + timedelta(days=20),
                "registrar_name": "KFin Technologies Limited",
                "registrar_code": "NTPCGREEN",
                "pe_ratio": 34.0,
                "industry_pe": 40.0,
                "ronw": 18.2,
                "eps": 3.18,
                "sector": "Renewable Energy & Solar",
                "revenue_growth_yoy": 42.5,
                "pat_growth_yoy": 55.0,
                "debt_to_equity": 0.45,
                "pat_margin_pct": 21.0,
                "promoter_holding_pre": 100.0,
                "promoter_holding_post": 85.0,
                "gmp": {"gmp_amount": 12.0, "gmp_percentage": 11.11, "source": "investorgain"},
                "sub": {"qib_multiple": 0.0, "nii_multiple": 0.0, "retail_multiple": 0.0, "total_multiple": 0.0}
            },
            {
                "symbol": "HYUNDAI",
                "company_name": "Hyundai Motor India Ltd",
                "ipo_type": IPOType.MAINBOARD,
                "status": IPOStatus.UPCOMING,
                "price_band_low": 1865.0,
                "price_band_high": 1960.0,
                "issue_price": 1960.0,
                "lot_size": 7,
                "issue_size_crores": 27870.0,
                "fresh_issue_crores": 0.0,
                "ofs_crores": 27870.0,
                "open_date": today + timedelta(days=12),
                "close_date": today + timedelta(days=14),
                "allotment_date": today + timedelta(days=17),
                "listing_date": today + timedelta(days=21),
                "registrar_name": "KFin Technologies Limited",
                "registrar_code": "HYUNDAI",
                "pe_ratio": 26.2,
                "industry_pe": 28.5,
                "ronw": 29.5,
                "eps": 74.8,
                "sector": "Automobile & Passenger Vehicles",
                "revenue_growth_yoy": 15.8,
                "pat_growth_yoy": 28.7,
                "debt_to_equity": 0.12,
                "pat_margin_pct": 11.2,
                "promoter_holding_pre": 100.0,
                "promoter_holding_post": 82.5,
                "gmp": {"gmp_amount": 85.0, "gmp_percentage": 4.34, "source": "chittorgarh"},
                "sub": {"qib_multiple": 0.0, "nii_multiple": 0.0, "retail_multiple": 0.0, "total_multiple": 0.0}
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
                ipo_obj = IPO(**item, is_seed=True)
                session.add(ipo_obj)
                await session.flush()
                count += 1
            else:
                ipo_obj = existing
                ipo_obj.is_seed = True
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
        Runs complete sync:
        1. Scrapes InvestorGain and IPOWatch (second source) with robots.txt compliance and rate limits.
        2. Matches scraped rows via aliases and normalized rapidfuzz with cross-checks.
        3. Saves readings per source into IPOGmp without overwriting.
        4. Matches subscription data (including InvestorGain total multiple fallback).
        5. Computes 12-hour consensus median GMP with source disagreement tracking.
        6. Recomputes composite scores with missing-data proportional scaling.
        7. Triggers GMP data quality alerts (Telegram and banner) if sources fail or <50% live IPOs fresh.
        """
        logger.info("Starting multi-source market data sync (InvestorGain + IPOWatch)...")
        now_sync = datetime.now(timezone.utc)

        # 1. Scrape InvestorGain
        try:
            ig_records = await cls.scrape_gmp_feed()
        except Exception as exc:
            logger.error(f"Error scraping InvestorGain: {exc}")
            ig_records = []

        # 2. Scrape IPOWatch
        try:
            iw_records = await IPOWatchScraper.fetch_feed()
        except Exception as exc:
            logger.error(f"Error scraping IPOWatch: {exc}")
            iw_records = []

        # 3. Scrape Chittorgarh Subscriptions
        try:
            sub_records = await cls.scrape_subscription_feed()
        except Exception as exc:
            logger.error(f"Error scraping subscription feed: {exc}")
            sub_records = []

        # 4. Correct stored statuses and query target IPOs (Live, Upcoming, and Closed until listing date, excluding seeds)
        from app.services.scheduler import correct_ipo_statuses
        await correct_ipo_statuses(session)

        today_dt = date.today()
        stmt = select(IPO).where(
            IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING, IPOStatus.CLOSED]),
            IPO.is_seed.is_(False),
            or_(IPO.listing_date.is_(None), IPO.listing_date >= today_dt)
        )
        result = await session.execute(stmt)
        active_ipos = result.scalars().all()

        # 5. Match GMP rows against target IPOs
        ig_matched, ig_unmatched = await match_gmp_records_to_ipos(
            session, ig_records, active_ipos, source_name="investorgain"
        )
        iw_matched, iw_unmatched = await match_gmp_records_to_ipos(
            session, iw_records, active_ipos, source_name="ipowatch"
        )

        # 6. Save each reading in ipo_gmp with source and recorded_at
        all_matched_pairs = ig_matched + iw_matched
        for ipo, scraped_item in all_matched_pairs:
            src = scraped_item.get("source", "market")
            gmp_amt = scraped_item.get("gmp_amount")
            gmp_pct = scraped_item.get("gmp_percentage")
            base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low or scraped_item.get("price") or 0.0

            if gmp_amt is None and gmp_pct is not None and base_price > 0:
                gmp_amt = round((gmp_pct / 100.0) * base_price, 2)
            if gmp_pct is None and gmp_amt is not None and base_price > 0:
                gmp_pct = round((gmp_amt / base_price) * 100.0, 2)

            # Never write default 0 if gmp_amt is None
            if gmp_amt is None:
                continue

            # Check latest reading for this source
            prev_stmt = (
                select(IPOGmp)
                .where(IPOGmp.ipo_id == ipo.id, IPOGmp.source == src)
                .order_by(IPOGmp.recorded_at.desc())
                .limit(1)
            )
            prev_gmp = (await session.execute(prev_stmt)).scalar_one_or_none()

            # Record if changed or no previous reading (deduplicate within 1 hour if values unchanged)
            is_gmp_dup = False
            if prev_gmp:
                val_same = (prev_gmp.gmp_amount == gmp_amt and prev_gmp.gmp_percentage == gmp_pct)
                prev_dt = prev_gmp.recorded_at if prev_gmp.recorded_at.tzinfo else prev_gmp.recorded_at.replace(tzinfo=timezone.utc)
                if val_same and (now_sync - prev_dt).total_seconds() < 3600:
                    is_gmp_dup = True

            if prev_gmp is None or (not is_gmp_dup and (prev_gmp.gmp_amount != gmp_amt or prev_gmp.gmp_percentage != gmp_pct)):
                new_gmp = IPOGmp(
                    ipo_id=ipo.id,
                    gmp_amount=gmp_amt,
                    gmp_percentage=gmp_pct or 0.0,
                    source=src,
                    recorded_at=now_sync
                )
                session.add(new_gmp)

        # 7. Match and record subscriptions
        for ipo in active_ipos:
            norm_name = normalize_for_gmp_match(ipo.company_name)
            matched_sub = next(
                (s for s in sub_records if norm_name and (norm_name in normalize_for_gmp_match(s["company_name"]) or normalize_for_gmp_match(s["company_name"]) in norm_name)),
                None
            )
            # If Chittorgarh sub not found, check if InvestorGain scraped item had subscription_total (e.g. 131.7x for HD Fire Protect)
            ig_item = next((item for target_ipo, item in ig_matched if target_ipo.id == ipo.id), None)

            tot_mult = None
            qib_mult = None
            nii_mult = None
            ret_mult = None

            if matched_sub:
                tot_mult = matched_sub.get("total_multiple")
                qib_mult = matched_sub.get("qib_multiple")
                nii_mult = matched_sub.get("nii_multiple")
                ret_mult = matched_sub.get("retail_multiple")
            elif ig_item and ig_item.get("subscription_total") is not None:
                tot_mult = ig_item.get("subscription_total")

            if tot_mult is not None or qib_mult is not None or ret_mult is not None:
                prev_sub_stmt = (
                    select(IPOSubscription)
                    .where(IPOSubscription.ipo_id == ipo.id)
                    .order_by(IPOSubscription.recorded_at.desc())
                    .limit(1)
                )
                prev_sub = (await session.execute(prev_sub_stmt)).scalar_one_or_none()
                is_sub_dup = False
                if prev_sub:
                    sub_val_same = (
                        prev_sub.total_multiple == tot_mult
                        and prev_sub.qib_multiple == qib_mult
                        and prev_sub.nii_multiple == nii_mult
                        and prev_sub.retail_multiple == ret_mult
                    )
                    prev_sub_dt = prev_sub.recorded_at if prev_sub.recorded_at.tzinfo else prev_sub.recorded_at.replace(tzinfo=timezone.utc)
                    if sub_val_same and (now_sync - prev_sub_dt).total_seconds() < 3600:
                        is_sub_dup = True

                if prev_sub is None or (not is_sub_dup and (
                    prev_sub.total_multiple != tot_mult
                    or prev_sub.qib_multiple != qib_mult
                    or prev_sub.nii_multiple != nii_mult
                    or prev_sub.retail_multiple != ret_mult
                )):
                    new_sub = IPOSubscription(
                        ipo_id=ipo.id,
                        qib_multiple=qib_mult,
                        nii_multiple=nii_mult,
                        retail_multiple=ret_mult,
                        total_multiple=tot_mult if tot_mult is not None else 0.0,
                        recorded_at=now_sync
                    )
                    session.add(new_sub)

        await session.flush()

        # 8. Consensus GMP Calculation and Score Recalculation
        updated_count = 0
        live_ipos_count = 0
        live_ipos_with_fresh_gmp = 0

        for ipo in active_ipos:
            # Latest subscription
            sub_stmt = select(IPOSubscription).where(IPOSubscription.ipo_id == ipo.id).order_by(IPOSubscription.recorded_at.desc()).limit(1)
            latest_sub_obj = (await session.execute(sub_stmt)).scalar_one_or_none()

            # All recent GMP readings
            gmp_all_stmt = select(IPOGmp).where(IPOGmp.ipo_id == ipo.id).order_by(IPOGmp.recorded_at.desc())
            readings = (await session.execute(gmp_all_stmt)).scalars().all()
            consensus = ConsensusGmpService.calculate_consensus_from_readings(readings, now=now_sync)

            if ipo.status == IPOStatus.LIVE:
                live_ipos_count += 1
                if consensus["status"] == "fresh":
                    live_ipos_with_fresh_gmp += 1

            # Prepare GMP input for ScoringService:
            # Use consensus median if fresh; None if missing or stale (>24h)
            consensus_gmp_obj: Optional[IPOGmp] = None
            if consensus["status"] == "fresh" and consensus["gmp_amount"] is not None:
                consensus_gmp_obj = IPOGmp(
                    ipo_id=ipo.id,
                    gmp_amount=consensus["gmp_amount"],
                    gmp_percentage=consensus["gmp_percentage"],
                    source="consensus",
                    recorded_at=now_sync
                )

            # Recalculate score
            score_data = ScoringService.calculate_score(
                ipo=ipo,
                latest_subscription=latest_sub_obj,
                latest_gmp=consensus_gmp_obj
            )

            ipo.updated_at = now_sync

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
                valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
                filtered_score = {k: v for k, v in score_data.items() if k in valid_keys}
                session.add(IPOScore(ipo_id=ipo.id, calculated_at=now_sync, **filtered_score))

            updated_count += 1

        # 9. Step 9: GMP Data Quality Alert
        quality_status = cls.evaluate_gmp_quality(
            ig_count=len(ig_records),
            iw_count=len(iw_records),
            live_ipos_count=live_ipos_count,
            live_ipos_with_fresh_gmp=live_ipos_with_fresh_gmp
        )
        cls._gmp_quality_status = quality_status

        if quality_status["alert_active"]:
            if not cls._gmp_alert_active:
                cls._gmp_alert_active = True
                msg = f"⚠️ <b>IPO Market Data Alert</b>: {quality_status['message']} ({quality_status.get('reason', '')})"
                try:
                    await TelegramService.send_message(msg)
                except Exception as t_err:
                    logger.error(f"Failed to send Telegram alert for GMP quality: {t_err}")
        else:
            cls._gmp_alert_active = False

        await session.commit()
        return {
            "status": "success",
            "investorgain_scraped": len(ig_records),
            "investorgain_matched": len(ig_matched),
            "investorgain_unmatched": len(ig_unmatched),
            "ipowatch_scraped": len(iw_records),
            "ipowatch_matched": len(iw_matched),
            "ipowatch_unmatched": len(iw_unmatched),
            "subscription_scraped": len(sub_records),
            "ipos_updated": updated_count,
            "timestamp": datetime.now().isoformat()
        }
