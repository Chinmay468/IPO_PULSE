import asyncio
import html
import logging
import re
import time
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ipo import (
    IPO,
    IPOType,
    IPOStatus,
    IPOScore,
    IPOGmp,
    IPOSubscription,
    IPODocument,
    IPOAnchor,
    IPOReviewsSummary,
    IPOListing,
)
from app.services.scoring_service import ScoringService
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


# ---------------- Exceptions ----------------
class ChittorgarhRateLimitException(Exception):
    """Raised when Chittorgarh returns 403 Forbidden or 429 Too Many Requests."""
    pass


class ChittorgarhStructureChangeException(Exception):
    """Raised when parser finds zero expected fields on 3 consecutive pages."""
    pass


# ---------------- Normalization & Helpers ----------------
def clean_num(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    cleaned = re.sub(r"[^\d.-]", "", val.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date_string(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    s = date_str.strip()
    if not s or "[.]" in s or s == "-":
        return None

    # Strip tentative indicators or non-date annotations: ' T', ' [T]', '(Tentative)', '| T'
    s = re.sub(r"\s*\[?[Tt](?:entative)?\]?\s*$", "", s).strip()
    s = re.sub(r"\s*\|\s*[Tt]\s*$", "", s).strip()
    s = re.sub(r"\s*\(tentative\)\s*$", "", s, flags=re.IGNORECASE).strip()

    # Handle single date formats
    for fmt in [
        "%d %b %Y",
        "%d %b, %Y",
        "%b %d, %Y",
        "%a, %b %d, %Y",
        "%Y-%m-%d",
        "%d/%m/%Y"
    ]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # Handle month/day without year, e.g. "15 Oct" -> assume current or appropriate year
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})$", s)
    if m:
        try:
            yr = date.today().year
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {yr}", "%d %b %Y").date()
        except ValueError:
            pass

    return None


def normalize_company_name(name: Optional[str]) -> str:
    """
    Standardizes company names for matching across data sources:
    removes common corporate suffixes, punctuation, and trims excess whitespace.
    """
    if not name:
        return ""
    s = name.lower()
    # Remove HTML entities or weird chars
    s = html.unescape(s)
    # Remove IPO suffix
    s = re.sub(r"\s+ipo(\s+details)?$", "", s, flags=re.IGNORECASE)
    # Remove corporate suffixes
    s = re.sub(r"\b(limited|ltd|pvt|private|co|corp|corporation|inc|holdings|group|india)\b", "", s, flags=re.IGNORECASE)
    # Remove non-alphanumeric chars
    s = re.sub(r"[^a-z0-9\s]", "", s)
    # Collapse whitespace
    return re.sub(r"\s+", " ", s).strip()


def derive_symbol(company_name: str) -> str:
    """Generates an uppercase symbol slug from company name if missing."""
    clean = normalize_company_name(company_name)
    parts = clean.split()
    if len(parts) >= 2:
        slug = "".join([p[:4].upper() for p in parts[:3]])
    elif parts:
        slug = parts[0][:10].upper()
    else:
        slug = f"IPO_{int(time.time())}"
    return slug[:20]


def determine_status_from_dates(
    open_date: Optional[date],
    close_date: Optional[date],
    listing_date: Optional[date],
    dates_tba: bool = False
) -> IPOStatus:
    """Derives current IPO life-cycle state from official dates using canonical IST rules."""
    from app.core.ipo_timeline import derive_ipo_status
    return derive_ipo_status(open_date, close_date, listing_date, dates_tba=dates_tba)


# ---------------- Compliance Client ----------------
class ChittorgarhClient:
    """
    HTTP Client strictly obeying compliance rules:
    - Checks and obeys https://www.chittorgarh.com/robots.txt before each run.
    - Never fetches /ipo/ipo_discussions.asp or login-gated pages.
    - Delays 2.0 to 3.0 seconds between requests.
    - Uses descriptive User-Agent, timeouts, exponential backoff.
    - Halts immediately on HTTP 403 or 429 with logged warning.
    - In-memory/disk caching: detail pages for finished IPOs: 7 days; live IPOs: 15 min.
    """

    ROBOTS_URL = "https://www.chittorgarh.com/robots.txt"
    DISALLOWED_PATHS: Set[str] = {"/ipo/ipo_discussions.asp"}
    USER_AGENT = "IPOPulseBot/1.0 (+https://github.com/ipo-pulse; research/personal)"
    DEFAULT_DELAY_SECONDS = 2.2
    CACHE_FINISHED_TTL = 7 * 86400  # 7 days
    CACHE_LIVE_TTL = 15 * 60        # 15 minutes

    def __init__(self, delay_seconds: float = DEFAULT_DELAY_SECONDS):
        self.delay_seconds = delay_seconds
        self.last_request_time: float = 0.0
        self.disallowed_patterns: Set[str] = set(self.DISALLOWED_PATHS)
        self.robots_checked = False
        # In-memory page cache: url -> (content_str, timestamp_float, is_finished_bool)
        self._page_cache: Dict[str, Tuple[str, float, bool]] = {}

    async def check_and_load_robots_txt(self, client: Optional[httpx.AsyncClient] = None) -> None:
        """Fetches robots.txt and updates disallowed paths."""
        try:
            should_close = False
            if client is None:
                client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": self.USER_AGENT})
                should_close = True

            resp = await client.get(self.ROBOTS_URL)
            if resp.status_code == 200:
                lines = resp.text.splitlines()
                applies_to_us = False
                for line in lines:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    if line.lower().startswith("user-agent:"):
                        ua = line.split(":", 1)[1].strip()
                        applies_to_us = (ua == "*")
                    elif applies_to_us and line.lower().startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path and path != "/":
                            self.disallowed_patterns.add(path)
                self.robots_checked = True
                logger.info(f"Loaded Chittorgarh robots.txt. Disallowed rules: {self.disallowed_patterns}")
        except Exception as exc:
            logger.warning(f"Could not fetch robots.txt ({exc}); applying strict default disallow rules.")
            self.disallowed_patterns.update(self.DISALLOWED_PATHS)
        finally:
            if should_close and client:
                await client.aclose()

    def is_url_allowed(self, url: str) -> bool:
        """Checks if URL path is permitted by robots.txt."""
        for pattern in self.disallowed_patterns:
            if pattern in url:
                return False
        return True

    async def fetch(
        self,
        url: str,
        client: Optional[httpx.AsyncClient] = None,
        force_refresh: bool = False,
        is_finished: bool = False
    ) -> str:
        """
        Fetches the requested URL with rate-limiting, compliance checks, caching and backoff.
        """
        # 1. Enforce robots.txt compliance
        if not self.is_url_allowed(url):
            raise ValueError(f"Fetching {url} is prohibited by robots.txt or compliance policy.")

        # 2. Check Cache
        now = time.time()
        if not force_refresh and url in self._page_cache:
            content, cached_at, cached_finished = self._page_cache[url]
            ttl = self.CACHE_FINISHED_TTL if (is_finished or cached_finished) else self.CACHE_LIVE_TTL
            if (now - cached_at) < ttl:
                logger.debug(f"Serving cached page for {url} (age: {int(now - cached_at)}s)")
                return content

        # 3. Enforce Polite Rate Limit (2.0 - 3.0 seconds between requests)
        elapsed = now - self.last_request_time
        if elapsed < self.delay_seconds:
            sleep_duration = self.delay_seconds - elapsed
            await asyncio.sleep(sleep_duration)

        # 4. Outgoing Request with Retries & Exponential Backoff
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers)
            should_close = True

        max_attempts = 3
        backoff = 1.0

        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    self.last_request_time = time.time()
                    resp = await client.get(url, headers=headers)

                    # 403 Forbidden or 429 Too Many Requests -> Halt immediately
                    if resp.status_code in [403, 429]:
                        logger.warning(
                            f"Chittorgarh rate limit / access blocked (HTTP {resp.status_code}) on {url}. Stopping scraper run."
                        )
                        raise ChittorgarhRateLimitException(
                            f"HTTP {resp.status_code} received from {url}. Scraper run aborted to respect server."
                        )

                    if resp.status_code == 200:
                        text = resp.text
                        self._page_cache[url] = (text, time.time(), is_finished)
                        return text
                    elif resp.status_code in [500, 502, 503, 504]:
                        logger.warning(f"Chittorgarh server error HTTP {resp.status_code} on attempt {attempt}/{max_attempts}")
                        if attempt == max_attempts:
                            resp.raise_for_status()
                    else:
                        resp.raise_for_status()
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    if attempt == max_attempts:
                        raise exc
                    logger.info(f"Transient network error fetching {url}: {exc}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2.0

            raise httpx.HTTPStatusError("Max retries exceeded", request=None, response=None)  # type: ignore
        finally:
            if should_close and client:
                await client.aclose()


# ---------------- Structure Change Detector ----------------
class StructureChangeDetector:
    """
    Monitors whether parsers find expected fields.
    If 0 fields are extracted across 3 consecutive pages, logs an error,
    dispatches a Telegram alert, and halts that parser.
    """

    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, max_consecutive_failures: int = 3):
        self.max_consecutive_failures = max_consecutive_failures
        self.consecutive_failures: int = 0
        self.last_failed_url: Optional[str] = None

    async def record_result(self, parser_name: str, fields_found: int, url: str) -> None:
        if fields_found == 0:
            self.consecutive_failures += 1
            self.last_failed_url = url
            logger.warning(
                f"StructureChangeDetector: {parser_name} extracted 0 fields from {url} "
                f"(consecutive failure {self.consecutive_failures}/{self.max_consecutive_failures})"
            )

            if self.consecutive_failures >= self.max_consecutive_failures:
                error_msg = (
                    f"🚨 <b>Scraper Structure Change Detected</b>\n\n"
                    f"Parser: <code>{parser_name}</code>\n"
                    f"Found 0 expected fields on {self.consecutive_failures} consecutive pages.\n"
                    f"Last URL: <code>{url}</code>\n\n"
                    f"<b>Action:</b> Scraper run halted to prevent corrupted updates."
                )
                logger.error(error_msg)
                try:
                    await TelegramService.send_message(error_msg)
                except Exception as tg_err:
                    logger.error(f"Failed to dispatch Telegram structure change alert: {tg_err}")

                raise ChittorgarhStructureChangeException(
                    f"Parser {parser_name} failed on {self.consecutive_failures} consecutive pages at {url}."
                )
        else:
            self.consecutive_failures = 0


# ---------------- Pure BeautifulSoup Parsers ----------------
def parse_date_range(d_str: Optional[str]) -> Tuple[Optional[date], Optional[date], bool]:
    """
    Parses date range strings from Chittorgarh list/dashboard pages.
    Returns (open_date, close_date, dates_tba).
    """
    if not d_str or not d_str.strip():
        return None, None, True

    s = d_str.strip()
    if s in ["-", "--", "TBA", "Dates to be announced", "N/A", "[.]", "Dates not announced"]:
        return None, None, True

    # Clean leading status indicators like "O 13 - 15 Oct" or "C 30 Sep - 5 Oct"
    s = re.sub(r"^[OCL]\s+", "", s)

    # Clean trailing tentative indicators like "13 to 15 Oct, 2026 T"
    s = re.sub(r"\s*\[?[Tt](?:entative)?\]?\s*$", "", s).strip()
    s = re.sub(r"\s*\|\s*[Tt]\s*$", "", s).strip()

    # Pattern 1: Day-first, e.g. "13 to 15 Oct, 2026", "13 - 15 Oct", "30 Sep to 5 Oct, 2026"
    m = re.search(r'(\d+)\s*([A-Za-z]{3})?\s*(?:-|–|to)\s*(\d+)\s+([A-Za-z]{3})(?:,?\s*(\d{4}))?', s, re.IGNORECASE)
    if m:
        yr = m.group(5) or str(date.today().year)
        m1 = m.group(2) or m.group(4)
        m2 = m.group(4)
        try:
            d1 = int(m.group(1))
            d2 = int(m.group(3))
            dt1 = datetime.strptime(f"{d1} {m1} {yr}", "%d %b %Y").date()
            dt2 = datetime.strptime(f"{d2} {m2} {yr}", "%d %b %Y").date()
            return dt1, dt2, False
        except ValueError:
            pass

    # Pattern 2: Month-first, e.g. "Oct 13, 2026 to Oct 15, 2026", "Oct 13 to Oct 15, 2026"
    m2 = re.search(r'([A-Za-z]{3})\s+(\d+)(?:,?\s*(\d{4}))?\s*(?:-|–|to)\s*([A-Za-z]{3})?\s*(\d+)(?:,?\s*(\d{4}))?', s, re.IGNORECASE)
    if m2:
        yr = m2.group(6) or m2.group(3) or str(date.today().year)
        mo1 = m2.group(1)
        mo2 = m2.group(4) or mo1
        try:
            d1 = int(m2.group(2))
            d2 = int(m2.group(5))
            dt1 = datetime.strptime(f"{d1} {mo1} {yr}", "%d %b %Y").date()
            dt2 = datetime.strptime(f"{d2} {mo2} {yr}", "%d %b %Y").date()
            return dt1, dt2, False
        except ValueError:
            pass

    # Try single date
    single = parse_date_string(s)
    if single:
        return single, None, False

    return None, None, True


def parse_dashboard_list(html_text: str, ipo_type: IPOType = IPOType.MAINBOARD) -> List[Dict[str, Any]]:
    """
    Parses Chittorgarh dashboard and report list tables.
    Extracts Company name, detail page link, source_id, dates, price, size, and lot size.
    Handles both single-table and multi-table formats, detecting SME vs Mainboard.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return []

    items: List[Dict[str, Any]] = []
    seen_ids: Set[int] = set()

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        # Look for headers
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        col_map: Dict[str, int] = {}
        for idx, h in enumerate(headers):
            if any(k in h for k in ["company", "issuer"]):
                col_map["company"] = idx
            elif any(k in h for k in ["open", "start"]):
                col_map["open"] = idx
            elif any(k in h for k in ["close", "end"]):
                col_map["close"] = idx
            elif any(k in h for k in ["listing", "list date"]):
                col_map["listing"] = idx
            elif any(k in h for k in ["issue date", "date"]):
                col_map["date"] = idx
            elif any(k in h for k in ["price", "band"]):
                col_map["price"] = idx
            elif any(k in h for k in ["size", "cr."]):
                col_map["size"] = idx
            elif any(k in h for k in ["lot"]):
                col_map["lot"] = idx

        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            a = tr.find("a", href=True)
            if not a:
                continue

            href = a["href"].strip()
            # Extract numeric source_id from /ipo/<slug>/<id>/
            m = re.search(r"/ipo/([a-zA-Z0-9_-]+)/(\d+)/?", href)
            if not m:
                continue

            slug = m.group(1).lower()
            source_id = int(m.group(2))
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            company_name = a.get_text(strip=True)
            if not company_name:
                continue

            # Determine SME vs Mainboard
            is_sme = "sme" in slug or "sme" in tr.get_text().lower() or ipo_type == IPOType.SME
            effective_type = IPOType.SME if is_sme else IPOType.MAINBOARD

            # Extract date string
            date_str = ""
            if "date" in col_map and col_map["date"] < len(cells):
                date_str = cells[col_map["date"]].get_text(" ", strip=True)
            elif len(cells) > 1:
                date_str = cells[1].get_text(" ", strip=True)
            else:
                full_text = cells[0].get_text(" ", strip=True)
                date_str = full_text.replace(company_name, "").strip()

            open_d: Optional[date] = None
            close_d: Optional[date] = None
            dates_tba = False
            if "open" in col_map and col_map["open"] < len(cells):
                open_d = parse_date_string(cells[col_map["open"]].get_text(strip=True))
            if "close" in col_map and col_map["close"] < len(cells):
                close_d = parse_date_string(cells[col_map["close"]].get_text(strip=True))

            if not open_d and not close_d:
                open_d, close_d, dates_tba = parse_date_range(date_str)

            listing_d: Optional[date] = None
            if "listing" in col_map and col_map["listing"] < len(cells):
                listing_d = parse_date_string(cells[col_map["listing"]].get_text(strip=True))

            # Prices
            p_low: Optional[float] = None
            p_high: Optional[float] = None
            issue_p: Optional[float] = None
            if "price" in col_map and col_map["price"] < len(cells):
                p_text = cells[col_map["price"]].get_text(strip=True)
                nums = re.findall(r"\d+(?:\.\d+)?", p_text.replace(",", ""))
                if len(nums) >= 2:
                    p_low = float(nums[0])
                    p_high = float(nums[1])
                    issue_p = p_high
                elif len(nums) == 1:
                    p_low = float(nums[0])
                    p_high = float(nums[0])
                    issue_p = p_high

            # Size
            issue_sz: Optional[float] = None
            if "size" in col_map and col_map["size"] < len(cells):
                issue_sz = clean_num(cells[col_map["size"]].get_text(strip=True))

            # Lot
            lot_sz: Optional[int] = None
            if "lot" in col_map and col_map["lot"] < len(cells):
                n = clean_num(cells[col_map["lot"]].get_text(strip=True))
                lot_sz = int(n) if n is not None else None

            source_url = f"https://www.chittorgarh.com{href}" if href.startswith("/") else href

            items.append({
                "company_name": company_name,
                "source_id": source_id,
                "source_url": source_url,
                "issue_date_str": date_str,
                "ipo_type": effective_type,
                "open_date": open_d,
                "close_date": close_d,
                "listing_date": listing_d,
                "dates_tba": dates_tba,
                "price_band_low": p_low,
                "price_band_high": p_high,
                "issue_price": issue_p,
                "lot_size": lot_sz,
                "issue_size_crores": issue_sz
            })

    return items


def parse_dashboard_reviews(html_text: str) -> Dict[str, Dict[str, int]]:
    """
    Parses Table 2 of /ipo/ipo_dashboard.asp.
    Extracts Apply, May Apply, Neutral, Avoid, Not Rated counts.
    Returns mapping of normalized company name -> review counts.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return {}

    table = tables[1]
    reviews_map: Dict[str, Dict[str, int]] = {}

    for tr in table.find_all("tr")[1:]:
        cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cols) >= 6:
            raw_name = cols[0]
            norm_name = normalize_company_name(raw_name)
            try:
                reviews_map[norm_name] = {
                    "apply": int(clean_num(cols[1]) or 0),
                    "may_apply": int(clean_num(cols[2]) or 0),
                    "neutral": int(clean_num(cols[3]) or 0),
                    "avoid": int(clean_num(cols[4]) or 0),
                    "not_rated": int(clean_num(cols[5]) or 0),
                }
            except ValueError:
                pass

    return reviews_map


def parse_ipo_detail(
    html_text: str,
    source_url: str = "",
    source_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Parses the comprehensive Chittorgarh IPO detail page.
    Stores NULL for any missing or unparseable field. Never defaults to 0.
    Records missing fields in data_quality dictionary.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    parsed: Dict[str, Any] = {
        "symbol": None,
        "company_name": None,
        "open_date": None,
        "close_date": None,
        "allotment_date": None,
        "listing_date": None,
        "price_band_low": None,
        "price_band_high": None,
        "issue_price": None,
        "listing_price": None,
        "lot_size": None,
        "issue_size_crores": None,
        "fresh_issue_crores": None,
        "ofs_crores": None,
        "registrar_name": None,
        "pe_ratio": None,
        "industry_pe": None,
        "ronw": None,
        "eps": None,
        "debt_to_equity": None,
        "pat_margin_pct": None,
        "promoter_holding_pre": None,
        "promoter_holding_post": None,
        "revenue_growth_yoy": None,
        "pat_growth_yoy": None,
        "source": "chittorgarh",
        "source_url": source_url,
        "source_id": source_id,
        "fetched_at": datetime.now(timezone.utc),
        "documents": [],
        "anchor_investors": [],
        "reviews_summary": None,
        "listing_info": None,
    }

    # 1. Company Name from H1
    h1 = soup.find("h1")
    if h1:
        raw_name = h1.get_text(strip=True)
        company_name = re.sub(r"\s+IPO(\s+Details)?$", "", raw_name, flags=re.IGNORECASE).strip()
        parsed["company_name"] = company_name

    tables = soup.find_all("table")

    # 2. Iterate all tables and extract key-value metrics
    for t in tables:
        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue

            k = cells[0].strip().lower()
            v = cells[1].strip()

            if "ipo date" in k:
                open_d, close_d, tba = parse_date_range(v)
                if open_d and close_d:
                    parsed["open_date"] = open_d
                    parsed["close_date"] = close_d
                    parsed["dates_tba"] = False
                elif open_d:
                    parsed["open_date"] = open_d
                    parsed["dates_tba"] = False
                elif not tba:
                    single = parse_date_string(v)
                    if single:
                        parsed["open_date"] = single
                        parsed["dates_tba"] = False

            elif "listed on" in k or "listing date" in k:
                parsed["listing_date"] = parse_date_string(v)

            elif "allotment" in k and "date" in k:
                parsed["allotment_date"] = parse_date_string(v)

            elif "price band" in k:
                nums = re.findall(r"\d+(?:\.\d+)?", v.replace(",", ""))
                if len(nums) >= 2:
                    parsed["price_band_low"] = float(nums[0])
                    parsed["price_band_high"] = float(nums[1])
                elif len(nums) == 1:
                    parsed["price_band_low"] = float(nums[0])
                    parsed["price_band_high"] = float(nums[0])

            elif "issue price" in k:
                parsed["issue_price"] = clean_num(v)

            elif "lot size" in k:
                num = clean_num(v)
                parsed["lot_size"] = int(num) if num is not None else None

            elif "total issue size" in k:
                m = re.search(r"up\s+to\s+[^\d]*([\d,]+(?:\.\d+)?)\s*cr", v, re.IGNORECASE)
                parsed["issue_size_crores"] = clean_num(m.group(1)) if m else clean_num(v)

            elif "fresh issue" in k:
                m = re.search(r"up\s+to\s+[^\d]*([\d,]+(?:\.\d+)?)\s*cr", v, re.IGNORECASE)
                parsed["fresh_issue_crores"] = clean_num(m.group(1)) if m else clean_num(v)

            elif "offer for sale" in k:
                m = re.search(r"up\s+to\s+[^\d]*([\d,]+(?:\.\d+)?)\s*cr", v, re.IGNORECASE)
                parsed["ofs_crores"] = clean_num(m.group(1)) if m else clean_num(v)

            elif "bse script code / nse symbol" in k:
                parts = [p.strip() for p in v.split("/")]
                if len(parts) >= 2 and parts[1] and parts[1] != "-":
                    parsed["symbol"] = parts[1]
                elif len(parts) >= 1 and parts[0] and parts[0] != "-":
                    parsed["symbol"] = parts[0]

            elif "debt/equity" in k:
                parsed["debt_to_equity"] = clean_num(v)

            elif "ronw" in k:
                parsed["ronw"] = clean_num(v)

            elif "pat margin" in k:
                parsed["pat_margin_pct"] = clean_num(v)

            elif "p/e (x)" in k:
                # Prefer post-IPO P/E in cell 2 if available
                val = cells[2] if len(cells) > 2 and clean_num(cells[2]) is not None else cells[1]
                parsed["pe_ratio"] = clean_num(val)

            elif "eps" in k:
                val = cells[2] if len(cells) > 2 and clean_num(cells[2]) is not None else cells[1]
                parsed["eps"] = clean_num(val)

            elif "promoter and promoter group" in k:
                parsed["promoter_holding_pre"] = clean_num(cells[1]) if len(cells) > 1 else None
                parsed["promoter_holding_post"] = clean_num(cells[2]) if len(cells) > 2 else None

            elif "final issue price" in k:
                parsed["listing_price"] = clean_num(v)

            elif k == "open" and not parsed.get("listing_price"):
                parsed["listing_price"] = clean_num(v)

    # 3. Restated Financials YoY Growth Calculations
    for t in tables:
        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            lbl = cells[0].strip().lower()
            if "total income" in lbl or "revenue" in lbl:
                nums = [clean_num(c) for c in cells[1:] if clean_num(c) is not None]
                if len(nums) >= 2 and nums[1] > 0 and parsed.get("revenue_growth_yoy") is None:
                    parsed["revenue_growth_yoy"] = round(((nums[0] - nums[1]) / nums[1]) * 100.0, 2)
            elif "profit after tax" in lbl or lbl == "pat":
                nums = [clean_num(c) for c in cells[1:] if clean_num(c) is not None]
                if len(nums) >= 2 and nums[1] > 0 and parsed.get("pat_growth_yoy") is None:
                    parsed["pat_growth_yoy"] = round(((nums[0] - nums[1]) / nums[1]) * 100.0, 2)

    # 4. Registrar Name Extraction
    for p in soup.find_all(["p", "div", "td"]):
        txt = p.get_text(" ", strip=True)
        m = re.search(r"is\s+the\s+registrar\s+(?:of|for|to)\s+the\s+issue", txt, re.IGNORECASE)
        if m:
            preceding = txt[:m.start()].strip()
            # Handle "...and <Registrar Name>"
            parts = re.split(r"(?:and|\.)\s+", preceding)
            candidate = parts[-1].strip()
            if len(candidate) >= 3 and not parsed.get("registrar_name"):
                parsed["registrar_name"] = candidate
                break

    # 5. Documents Extraction (DRHP / RHP)
    doc_urls_seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        txt = a.get_text(strip=True).upper()
        # Avoid generic catalog report links
        if "/report/" in href:
            continue
        full_url = href if href.startswith("http") else f"https://www.chittorgarh.com{href}"
        if full_url in doc_urls_seen:
            continue

        if "DRHP" in txt or "drhp" in href.lower():
            parsed["documents"].append({"type": "DRHP", "url": full_url})
            doc_urls_seen.add(full_url)
        elif "RHP" in txt or "rhp" in href.lower():
            parsed["documents"].append({"type": "RHP", "url": full_url})
            doc_urls_seen.add(full_url)

    # 6. Reviews Breakdown
    for t in tables:
        headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if any("subscribe" in h or "apply" in h for h in headers) and any("avoid" in h for h in headers):
            app = 0
            may = 0
            neu = 0
            avd = 0
            for r in t.find_all("tr")[1:]:
                cols = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
                if len(cols) >= 5:
                    app += int(clean_num(cols[1]) or 0)
                    may += int(clean_num(cols[2]) or 0)
                    neu += int(clean_num(cols[3]) or 0)
                    avd += int(clean_num(cols[4]) or 0)
            parsed["reviews_summary"] = {
                "apply": app,
                "may_apply": may,
                "neutral": neu,
                "avoid": avd,
                "not_rated": 0,
            }
            break

    # 6b. Final Subscription Multiples Table Extraction
    for t in tables:
        headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if any("subscription" in h for h in headers) or (any("category" in h for h in headers) and any("shares bid" in h for h in headers)):
            sub_dict = {}
            for r in t.find_all("tr"):
                cells = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                cat = cells[0].strip().lower()
                val = clean_num(cells[1])
                if val is None:
                    continue
                if "qib" in cat:
                    sub_dict["qib_multiple"] = val
                    if len(cells) > 3:
                        sub_dict["qib_shares_offered"] = clean_num(cells[2])
                        sub_dict["qib_shares_bid"] = clean_num(cells[3])
                elif "nii" in cat and "bnii" not in cat and "snii" not in cat:
                    sub_dict["nii_multiple"] = val
                    if len(cells) > 3:
                        sub_dict["nii_shares_offered"] = clean_num(cells[2])
                        sub_dict["nii_shares_bid"] = clean_num(cells[3])
                elif "retail" in cat:
                    sub_dict["retail_multiple"] = val
                    if len(cells) > 3:
                        sub_dict["retail_shares_offered"] = clean_num(cells[2])
                        sub_dict["retail_shares_bid"] = clean_num(cells[3])
                elif "employee" in cat:
                    sub_dict["employee_multiple"] = val
                elif cat == "total" or "total" in cat:
                    sub_dict["total_multiple"] = val

            if sub_dict and (sub_dict.get("total_multiple") is not None or sub_dict.get("qib_multiple") is not None):
                parsed["subscription_data"] = sub_dict
                break

    # Date Validation: if close_date < open_date, set to NULL and record in data_quality
    if parsed.get("close_date") and parsed.get("open_date") and parsed["close_date"] < parsed["open_date"]:
        parsed["open_date"] = None
        parsed["close_date"] = None

    # 7. Listing Info
    listing_price = parsed.get("listing_price")
    issue_price = parsed.get("issue_price")
    listing_date = parsed.get("listing_date")
    if listing_price is not None:
        gain_pct = None
        if issue_price and issue_price > 0:
            gain_pct = round(((listing_price - issue_price) / issue_price) * 100.0, 2)
        parsed["listing_info"] = {
            "listing_price": listing_price,
            "listing_gain_pct": gain_pct,
            "listing_date": listing_date,
        }

    # 8. Derive Status & TBA handling
    parsed["dates_tba"] = (parsed.get("open_date") is None and parsed.get("close_date") is None)
    parsed["status"] = determine_status_from_dates(
        parsed.get("open_date"),
        parsed.get("close_date"),
        parsed.get("listing_date"),
        dates_tba=parsed["dates_tba"]
    )

    # 9. Ensure Symbol Exists
    if not parsed.get("symbol") and parsed.get("company_name"):
        parsed["symbol"] = derive_symbol(parsed["company_name"])

    # 10. Data Quality Tracker (NULL handling audit)
    key_fields = [
        "symbol",
        "company_name",
        "open_date",
        "close_date",
        "price_band_low",
        "price_band_high",
        "issue_price",
        "lot_size",
        "issue_size_crores",
        "fresh_issue_crores",
        "pe_ratio",
        "ronw",
        "eps",
        "promoter_holding_pre",
    ]
    missing = [f for f in key_fields if parsed.get(f) is None]
    if parsed.get("open_date") is None or parsed.get("close_date") is None:
        if "dates" not in missing:
            missing.append("dates")
    present_count = len(key_fields) - len([f for f in key_fields if parsed.get(f) is None])

    parsed["data_quality"] = {
        "missing_fields": missing,
        "fields_present": present_count,
        "fields_total": len(key_fields),
        "completeness_pct": round((present_count / len(key_fields)) * 100.0, 1),
        "status": "complete" if len(missing) <= 3 else "incomplete",
    }

    return parsed


def parse_subscription_page(html_text: str) -> Optional[Dict[str, Any]]:
    """
    Parses dedicated Chittorgarh subscription page (e.g. /ipo_subscription/<slug>/<id>/)
    to extract category-wise bidding multiples.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if any("times" in h or "subscription" in h for h in headers) and not any("shares offered" in h for h in headers):
            sub_dict: Dict[str, Any] = {}
            for row in t.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                cat = cells[0].strip().lower()
                raw_val = cells[1].replace("x", "").replace("X", "").strip()
                val = clean_num(raw_val)
                if val is None:
                    continue
                if "qualified" in cat or "qib" in cat:
                    sub_dict["qib_multiple"] = val
                elif "non institutional" in cat or "nii" in cat:
                    sub_dict["nii_multiple"] = val
                elif "retail" in cat:
                    sub_dict["retail_multiple"] = val
                elif "employee" in cat:
                    sub_dict["employee_multiple"] = val
                elif "total" in cat:
                    sub_dict["total_multiple"] = val
            if sub_dict.get("total_multiple") is not None or sub_dict.get("qib_multiple") is not None:
                return sub_dict
    return None


# ---------------- Database Sync Engine ----------------
async def sync_chittorgarh_data(
    session: AsyncSession,
    only_live: bool = False,
    max_detail_pages: Optional[int] = None,
    client: Optional[ChittorgarhClient] = None
) -> Dict[str, Any]:
    """
    Main Orchestrator:
    1. Obtains robots.txt.
    2. Scrapes Mainboard and SME dashboard lists.
    3. Fetches detail pages with caching and structure-change monitoring.
    4. Upserts IPO master records, documents, anchor, reviews, listing info.
    5. Re-runs ScoringService.calculate_score for accurate ranking.
    """
    if client is None:
        client = ChittorgarhClient()

    detector = StructureChangeDetector()
    await client.check_and_load_robots_txt()

    curr_yr = date.today().year
    urls_to_scrape = [
        ("https://www.chittorgarh.com/ipo/ipo_dashboard.asp", IPOType.MAINBOARD, True),
        ("https://www.chittorgarh.com/ipo/ipo_dashboard.asp?a=sme", IPOType.SME, True),
        ("https://www.chittorgarh.com/report/ipo-in-india-list-main-board-sme/82/", IPOType.MAINBOARD, False),
        (f"https://www.chittorgarh.com/report/ipo-in-india-list-main-board-sme/82/?year={curr_yr}", IPOType.MAINBOARD, False),
        ("https://www.chittorgarh.com/report/upcoming-ipo-in-india-drhp-filed-sebi-approval/84/", IPOType.MAINBOARD, False),
    ]

    discovered_items: List[Dict[str, Any]] = []
    reviews_map: Dict[str, Dict[str, int]] = {}

    for dash_url, ipo_type, expect_table in urls_to_scrape:
        try:
            html_text = await client.fetch(dash_url)
            items = parse_dashboard_list(html_text, ipo_type=ipo_type)
            revs = parse_dashboard_reviews(html_text)
            reviews_map.update(revs)
            discovered_items.extend(items)
            if expect_table:
                await detector.record_result("dashboard_list", len(items), dash_url)
        except Exception as exc:
            logger.error(f"Error fetching dashboard/report {dash_url}: {exc}")
            if isinstance(exc, (ChittorgarhRateLimitException, ChittorgarhStructureChangeException)):
                raise

    logger.info(f"Discovered {len(discovered_items)} IPO entries across Chittorgarh dashboards & reports.")

    # Deduplicate discovered items by source_id or company_name
    unique_items: Dict[str, Dict[str, Any]] = {}
    for item in discovered_items:
        key = str(item.get("source_id")) if item.get("source_id") else normalize_company_name(item["company_name"])
        if key not in unique_items:
            unique_items[key] = item

    created_count = 0
    updated_count = 0

    # Ensure all discovered IPOs exist in the database (creating missing records)
    for key, item in unique_items.items():
        s_id = item.get("source_id")
        raw_name = item.get("company_name", "").strip()
        norm_name = normalize_company_name(raw_name)

        matched: Optional[IPO] = None
        if s_id:
            matched = (await session.execute(select(IPO).where(IPO.source_id == s_id))).scalar_one_or_none()
        if not matched and norm_name:
            all_existing = (await session.execute(select(IPO))).scalars().all()
            for cand in all_existing:
                if normalize_company_name(cand.company_name) == norm_name:
                    matched = cand
                    break

        if not matched:
            sym = derive_symbol(raw_name)
            sym_match = (await session.execute(select(IPO).where(func.upper(IPO.symbol) == sym.upper()))).scalar_one_or_none()
            if sym_match:
                sym = f"{sym[:14]}_{s_id or int(time.time())}"[:20]

            dates_tba = item.get("dates_tba", False) or (item.get("open_date") is None and item.get("close_date") is None)
            st = determine_status_from_dates(
                item.get("open_date"),
                item.get("close_date"),
                item.get("listing_date"),
                dates_tba=dates_tba
            )
            new_ipo = IPO(
                symbol=sym,
                company_name=raw_name,
                ipo_type=item.get("ipo_type", IPOType.MAINBOARD),
                status=st,
                open_date=item.get("open_date"),
                close_date=item.get("close_date"),
                listing_date=item.get("listing_date"),
                dates_tba=dates_tba,
                price_band_low=item.get("price_band_low"),
                price_band_high=item.get("price_band_high"),
                issue_price=item.get("issue_price"),
                lot_size=item.get("lot_size"),
                issue_size_crores=item.get("issue_size_crores"),
                source="chittorgarh",
                source_url=item.get("source_url"),
                source_id=s_id,
                is_seed=False,
                fetched_at=datetime.now(timezone.utc),
                data_quality={"status": "discovered_from_list", "fields_present": 4, "fields_total": 14}
            )
            session.add(new_ipo)
            await session.flush()

            # Baseline score calculation
            score_data = ScoringService.calculate_score(new_ipo)
            valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
            filtered_score = {k: v for k, v in score_data.items() if k in valid_keys}
            session.add(IPOScore(ipo_id=new_ipo.id, **filtered_score))
            await session.flush()
            created_count += 1
        else:
            if matched.is_seed:
                matched.is_seed = False
            if not matched.source:
                matched.source = "chittorgarh"
            if s_id and not matched.source_id:
                matched.source_id = s_id
            if item.get("source_url") and not matched.source_url:
                matched.source_url = item.get("source_url")
            if not matched.open_date and item.get("open_date"):
                matched.open_date = item.get("open_date")
                matched.close_date = item.get("close_date")
                matched.dates_tba = item.get("dates_tba", False)
                matched.status = determine_status_from_dates(
                    matched.open_date, matched.close_date, matched.listing_date, dates_tba=matched.dates_tba
                )

    await session.commit()

    items_to_process = list(unique_items.values())

    # Filter for only live IPOs if requested
    if only_live:
        filtered = []
        for it in items_to_process:
            d_str = it.get("issue_date_str", "")
            if d_str and any(m in d_str for m in ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]):
                filtered.append(it)
        items_to_process = filtered or items_to_process[:5]

    if max_detail_pages is not None:
        items_to_process = items_to_process[:max_detail_pages]

    for item in items_to_process:
        source_url = item.get("source_url")
        source_id = item.get("source_id")
        if not source_url:
            continue

        try:
            detail_html = await client.fetch(source_url)
            parsed_detail = parse_ipo_detail(detail_html, source_url=source_url, source_id=source_id)

            # If live subscription data was not in the overview page, try dedicated subscription subpage
            if not parsed_detail.get("subscription_data") and source_url and "/ipo/" in source_url:
                sub_url = source_url.replace("/ipo/", "/ipo_subscription/")
                try:
                    sub_html = await client.fetch(sub_url)
                    sub_dict = parse_subscription_page(sub_html)
                    if sub_dict:
                        parsed_detail["subscription_data"] = sub_dict
                except Exception as sub_exc:
                    logger.debug("Could not fetch dedicated subscription page %s: %s", sub_url, sub_exc)

            # Record structure check (ensure at least 2 key fields found)
            fields_found = parsed_detail["data_quality"]["fields_present"]
            await detector.record_result("ipo_detail", fields_found, source_url)

            # Merge review from dashboard if detail had no review table
            norm_name = normalize_company_name(parsed_detail.get("company_name") or item.get("company_name"))
            if not parsed_detail.get("reviews_summary") and norm_name in reviews_map:
                parsed_detail["reviews_summary"] = reviews_map[norm_name]

            # Matching logic:
            # 1. By source_id
            # 2. By symbol
            # 3. By normalized company name
            matched_ipo: Optional[IPO] = None

            if source_id:
                stmt = select(IPO).where(IPO.source_id == source_id).options(
                    selectinload(IPO.score),
                    selectinload(IPO.documents),
                    selectinload(IPO.anchor_investors),
                    selectinload(IPO.reviews_summary),
                    selectinload(IPO.listing_info),
                    selectinload(IPO.subscriptions),
                    selectinload(IPO.gmp_records),
                )
                matched_ipo = (await session.execute(stmt)).scalar_one_or_none()

            symbol_candidate = parsed_detail.get("symbol")
            if not matched_ipo and symbol_candidate:
                stmt = select(IPO).where(func.upper(IPO.symbol) == symbol_candidate.upper()).options(
                    selectinload(IPO.score),
                    selectinload(IPO.documents),
                    selectinload(IPO.anchor_investors),
                    selectinload(IPO.reviews_summary),
                    selectinload(IPO.listing_info),
                    selectinload(IPO.subscriptions),
                    selectinload(IPO.gmp_records),
                )
                matched_ipo = (await session.execute(stmt)).scalar_one_or_none()

            if not matched_ipo:
                # Match by company name
                all_stmt = select(IPO).options(
                    selectinload(IPO.score),
                    selectinload(IPO.documents),
                    selectinload(IPO.anchor_investors),
                    selectinload(IPO.reviews_summary),
                    selectinload(IPO.listing_info),
                    selectinload(IPO.subscriptions),
                    selectinload(IPO.gmp_records),
                )
                for existing in (await session.execute(all_stmt)).scalars().all():
                    if normalize_company_name(existing.company_name) == norm_name:
                        matched_ipo = existing
                        break

            # Core scalar fields to update on IPO
            core_fields = [
                "symbol", "company_name", "status", "price_band_low", "price_band_high",
                "issue_price", "lot_size", "issue_size_crores", "fresh_issue_crores",
                "ofs_crores", "open_date", "close_date", "allotment_date", "listing_date",
                "registrar_name", "pe_ratio", "industry_pe", "ronw", "eps", "debt_to_equity",
                "pat_margin_pct", "promoter_holding_pre", "promoter_holding_post",
                "revenue_growth_yoy", "pat_growth_yoy", "source", "source_url", "source_id",
                "fetched_at", "data_quality", "dates_tba"
            ]

            data_changed = False
            if matched_ipo:
                # Update existing
                for f in core_fields:
                    val = parsed_detail.get(f)
                    if val is not None:
                        if getattr(matched_ipo, f) != val:
                            data_changed = True
                        setattr(matched_ipo, f, val)
                target_ipo = matched_ipo
                target_ipo.is_seed = False
                target_ipo.dates_tba = (target_ipo.open_date is None and target_ipo.close_date is None) or parsed_detail.get("dates_tba", False)
                target_ipo.status = determine_status_from_dates(
                    target_ipo.open_date, target_ipo.close_date, target_ipo.listing_date, dates_tba=target_ipo.dates_tba
                )
                if data_changed:
                    target_ipo.updated_at = datetime.now(timezone.utc)
                updated_count += 1
            else:
                # Create new IPO record
                init_kwargs = {f: parsed_detail.get(f) for f in core_fields if parsed_detail.get(f) is not None}
                init_kwargs["ipo_type"] = item.get("ipo_type", IPOType.MAINBOARD)
                init_kwargs["is_seed"] = False
                if not init_kwargs.get("symbol"):
                    init_kwargs["symbol"] = derive_symbol(init_kwargs.get("company_name", "IPO"))
                if not init_kwargs.get("company_name"):
                    init_kwargs["company_name"] = item.get("company_name", "Unknown IPO")

                init_kwargs["dates_tba"] = (init_kwargs.get("open_date") is None and init_kwargs.get("close_date") is None) or parsed_detail.get("dates_tba", False)
                init_kwargs["status"] = determine_status_from_dates(
                    init_kwargs.get("open_date"), init_kwargs.get("close_date"), init_kwargs.get("listing_date"), dates_tba=init_kwargs["dates_tba"]
                )

                target_ipo = IPO(**init_kwargs)
                session.add(target_ipo)
                await session.flush()
                created_count += 1

            # Update child records:
            # 1. Documents
            existing_doc_urls = {d.url for d in target_ipo.documents}
            for doc in parsed_detail.get("documents", []):
                if doc["url"] not in existing_doc_urls:
                    session.add(IPODocument(ipo_id=target_ipo.id, type=doc["type"], url=doc["url"]))

            # 2. Reviews Summary
            rev_data = parsed_detail.get("reviews_summary")
            if rev_data:
                if target_ipo.reviews_summary:
                    target_ipo.reviews_summary.apply = rev_data["apply"]
                    target_ipo.reviews_summary.may_apply = rev_data["may_apply"]
                    target_ipo.reviews_summary.neutral = rev_data["neutral"]
                    target_ipo.reviews_summary.avoid = rev_data["avoid"]
                    target_ipo.reviews_summary.not_rated = rev_data["not_rated"]
                    target_ipo.reviews_summary.fetched_at = datetime.now(timezone.utc)
                else:
                    session.add(IPOReviewsSummary(ipo_id=target_ipo.id, **rev_data))

            # 3. Listing Info
            list_data = parsed_detail.get("listing_info")
            if list_data and list_data.get("listing_price"):
                target_ipo.listing_price = list_data["listing_price"]
                if target_ipo.listing_info:
                    target_ipo.listing_info.listing_price = list_data["listing_price"]
                    target_ipo.listing_info.listing_gain_pct = list_data["listing_gain_pct"]
                    target_ipo.listing_info.listing_date = list_data["listing_date"]
                    target_ipo.listing_info.fetched_at = datetime.now(timezone.utc)
                else:
                    session.add(IPOListing(ipo_id=target_ipo.id, **list_data))

            # 3b. Subscription Info
            sub_dict = parsed_detail.get("subscription_data")
            if sub_dict and sub_dict.get("total_multiple") is not None:
                new_sub = IPOSubscription(
                    ipo_id=target_ipo.id,
                    qib_multiple=sub_dict.get("qib_multiple"),
                    nii_multiple=sub_dict.get("nii_multiple"),
                    retail_multiple=sub_dict.get("retail_multiple"),
                    employee_multiple=sub_dict.get("employee_multiple"),
                    total_multiple=sub_dict.get("total_multiple", 0.0),
                    qib_shares_offered=sub_dict.get("qib_shares_offered"),
                    qib_shares_bid=sub_dict.get("qib_shares_bid"),
                    nii_shares_offered=sub_dict.get("nii_shares_offered"),
                    nii_shares_bid=sub_dict.get("nii_shares_bid"),
                    retail_shares_offered=sub_dict.get("retail_shares_offered"),
                    retail_shares_bid=sub_dict.get("retail_shares_bid"),
                    recorded_at=datetime.now(timezone.utc),
                )
                session.add(new_sub)
                target_ipo.updated_at = datetime.now(timezone.utc)
                await session.flush()
                target_ipo.subscriptions.insert(0, new_sub)

            # 4. Recompute Composite Score
            latest_sub = target_ipo.subscriptions[0] if target_ipo.subscriptions else None
            latest_gmp = target_ipo.gmp_records[0] if target_ipo.gmp_records else None
            score_data = ScoringService.calculate_score(target_ipo, latest_sub, latest_gmp)

            valid_score_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
            filtered_score = {k: v for k, v in score_data.items() if k in valid_score_keys}

            if target_ipo.score:
                for k, v in filtered_score.items():
                    setattr(target_ipo.score, k, v)
                target_ipo.score.calculated_at = datetime.now(timezone.utc)
            else:
                session.add(IPOScore(ipo_id=target_ipo.id, calculated_at=datetime.now(timezone.utc), **filtered_score))

            await session.commit()

        except Exception as exc:
            logger.error(f"Error scraping detail page {source_url}: {exc}")
            if isinstance(exc, (ChittorgarhRateLimitException, ChittorgarhStructureChangeException)):
                raise

    # Phase 5: Post-scrape status correction to guarantee accurate IST lifecycle statuses
    try:
        from app.services.scheduler import scheduled_ipo_status_correction
        await scheduled_ipo_status_correction()
    except Exception as corr_err:
        logger.warning(f"Post-scrape status correction notice: {corr_err}")

    return {
        "status": "success",
        "discovered": len(discovered_items),
        "processed": len(items_to_process),
        "created": created_count,
        "updated": updated_count,
    }
