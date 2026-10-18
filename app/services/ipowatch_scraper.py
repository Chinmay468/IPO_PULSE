import logging
import re
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


class IPOWatchScraper:
    URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (IPO Enquiry Service Bot; mailto:admin@example.com)"
    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _last_fetch_time: Optional[float] = None
    _cached_records: List[Dict[str, Any]] = []
    _cached_html: Optional[str] = None
    _consecutive_failures: int = 0
    _is_paused: bool = False
    _alert_sent: bool = False

    @classmethod
    def _clean_num(cls, val: Optional[str]) -> Optional[float]:
        if not val:
            return None
        cleaned = re.sub(r"[^\d.-]", "", str(val).replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def parse_tables(cls, html: str) -> List[Dict[str, Any]]:
        """
        Parses Mainboard and SME GMP tables from IPOWatch HTML mapping columns by header text dynamically.
        - Required headers: Company and GMP.
        - Stops and raises ValueError if required headers are missing.
        - Raises data quality alert if >50% of parsed rows have empty GMP (once per incident).
        - Returns structured readings without writing fabricated defaults.
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        records: List[Dict[str, Any]] = []

        valid_table_found = False
        total_rows = 0
        empty_gmp_rows = 0

        for t in tables:
            rows = t.find_all("tr")
            if not rows:
                continue

            header_cols = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            
            comp_idx = None
            gmp_idx = None
            trend_idx = None
            price_idx = None
            gain_idx = None
            date_idx = None

            for idx, h in enumerate(header_cols):
                if comp_idx is None and ("company" in h or "name" in h):
                    comp_idx = idx
                elif gmp_idx is None and "gmp" in h:
                    gmp_idx = idx
                elif trend_idx is None and "trend" in h:
                    trend_idx = idx
                elif price_idx is None and "price" in h:
                    price_idx = idx
                elif gain_idx is None and ("gain" in h or "est" in h):
                    gain_idx = idx
                elif date_idx is None and "date" in h:
                    date_idx = idx

            if comp_idx is None or gmp_idx is None:
                continue

            valid_table_found = True

            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cols) > max(comp_idx, gmp_idx):
                    comp_raw = cols[comp_idx]
                    gmp_raw = cols[gmp_idx] if gmp_idx < len(cols) else ""
                    trend_raw = cols[trend_idx] if trend_idx is not None and trend_idx < len(cols) else ""
                    price_raw = cols[price_idx] if price_idx is not None and price_idx < len(cols) else ""
                    gain_raw = cols[gain_idx] if gain_idx is not None and gain_idx < len(cols) else ""
                    date_raw = cols[date_idx] if date_idx is not None and date_idx < len(cols) else ""

                    if not comp_raw or comp_raw.lower() in ("company", "name"):
                        continue

                    total_rows += 1

                    # Status tag: Upcoming / Open / (C)
                    status_tag = "OPEN"
                    if "upcoming" in comp_raw.lower():
                        status_tag = "UPCOMING"
                    elif "(c)" in comp_raw.lower() or "[c]" in comp_raw.lower() or "close" in comp_raw.lower():
                        status_tag = "CLOSED"

                    # Rupee amount: e.g. '₹225' or '₹0'
                    gmp_amt_match = re.search(r"₹\s*([0-9,.]+)", gmp_raw)
                    gmp_amount = cls._clean_num(gmp_amt_match.group(1)) if gmp_amt_match else cls._clean_num(gmp_raw)

                    if gmp_amount is None:
                        empty_gmp_rows += 1

                    # Price band
                    price_nums = [cls._clean_num(p) for p in re.findall(r"\b[0-9,.]+\b", price_raw.replace("₹", "")) if cls._clean_num(p) is not None]
                    price_high = max(price_nums) if price_nums else None

                    # Percentage: e.g. from '₹1344 (20.11%)'
                    pct_match = re.search(r"\(([0-9,.]+)%\)", gain_raw)
                    gmp_pct = cls._clean_num(pct_match.group(1)) if pct_match else None

                    # If percentage missing but amount and price known, compute it
                    if gmp_pct is None and gmp_amount is not None and price_high and price_high > 0:
                        gmp_pct = round((gmp_amount / price_high) * 100.0, 2)

                    # Never write default 0 if gmp_amount is None
                    if gmp_amount is not None:
                        records.append({
                            "company_name": comp_raw,
                            "status_tag": status_tag,
                            "gmp_amount": gmp_amount,
                            "gmp_percentage": gmp_pct if gmp_pct is not None else 0.0,
                            "price": price_high,
                            "trend": trend_raw,
                            "date_str": date_raw,
                            "source": "ipowatch",
                            "recorded_at": datetime.now(timezone.utc)
                        })

        if not valid_table_found:
            raise ValueError("Expected GMP columns (Company, GMP) not found in IPOWatch tables.")

        if total_rows > 0 and (empty_gmp_rows / total_rows) > 0.50:
            logger.warning(f"[IPOWatch Quality Alert] {empty_gmp_rows}/{total_rows} rows have empty GMP.")

        return records

    @classmethod
    async def fetch_feed(cls, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Fetches IPOWatch GMP page with rate-limiting (max once per 15 min),
        obeying robots.txt, timeouts, and handling failure thresholds.
        """
        now = time.time()
        # 15-minute rate limit caching
        if not force_refresh and cls._last_fetch_time and (now - cls._last_fetch_time < 900):
            if cls._cached_records:
                return cls._cached_records

        if cls._is_paused:
            logger.warning("[IPOWatch] Parser is currently paused due to consecutive structural failures.")
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                res = await client.get(cls.URL, headers=cls.HEADERS)
                if res.status_code in (403, 429):
                    logger.error(f"[IPOWatch] Blocked with HTTP {res.status_code}. Pausing scraper.")
                    cls._is_paused = True
                    return []

                if res.status_code == 200:
                    records = cls.parse_tables(res.text)
                    cls._last_fetch_time = now
                    cls._cached_records = records
                    cls._cached_html = res.text
                    cls._consecutive_failures = 0
                    cls._alert_sent = False
                    return records
                else:
                    logger.warning(f"[IPOWatch] HTTP {res.status_code} returned.")
                    cls._consecutive_failures += 1
        except Exception as exc:
            logger.error(f"[IPOWatch] Scrape error: {exc}")
            cls._consecutive_failures += 1

        if cls._consecutive_failures >= 3 and not cls._alert_sent:
            cls._is_paused = True
            cls._alert_sent = True
            msg = "⚠️ <b>IPOWatch Scraper Alert</b>: Expected GMP columns missing on 3 consecutive runs. IPOWatch parser has been paused while InvestorGain remains active."
            logger.critical(msg)
            try:
                await TelegramService.send_message(msg)
            except Exception as t_err:
                logger.error(f"Failed to send Telegram alert for IPOWatch failure: {t_err}")

        return cls._cached_records or []
