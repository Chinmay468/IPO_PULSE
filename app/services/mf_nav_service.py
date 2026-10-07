"""
Mutual Fund NAV service.
Fetches daily AMFI NAV text file and falls back to mfapi.in for per-scheme history.
Includes timeouts, retries, in-memory caching, and stale-state preservation.
"""
from datetime import datetime, date, timezone
import logging
import time
from typing import Optional, Dict, Any, List, Tuple
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mutual_fund import MFScheme, MFNavHistory

logger = logging.getLogger(__name__)

AMFI_URL_PRIMARY = "https://portal.amfiindia.com/spages/NAVAll.txt"
AMFI_URL_FALLBACK = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI_BASE_URL = "https://api.mfapi.in/mf"

# In-memory cache for parsed AMFI NAV file
_amfi_cache: Dict[str, Any] = {
    "data_by_code": {},
    "data_by_isin": {},
    "timestamp": 0.0,
}
AMFI_CACHE_TTL_SECONDS = 3600  # 1 hour cache


def parse_amfi_nav_text(text: str) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """
    Parses AMFI NAVAll.txt into dictionaries keyed by scheme_code and isin.
    Handles both 8-column and 6-column formats.
    """
    by_code: Dict[str, dict] = {}
    by_isin: Dict[str, dict] = {}
    current_category: Optional[str] = None
    current_amc: Optional[str] = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Detect category header lines (e.g. Open Ended Schemes(Equity Scheme - Large Cap Fund))
        if line.startswith("Open Ended Schemes") or line.startswith("Close Ended Schemes") or line.startswith("Interval Fund"):
            current_category = line
            continue

        # Detect AMC headers (lines without semicolons)
        if ";" not in line:
            current_amc = line
            continue

        parts = [p.strip() for p in line.split(";")]
        # Skip table header line
        if len(parts) >= 6 and parts[0].lower() in ("scheme code", "code"):
            continue

        try:
            scheme_code = parts[0]
            isin_growth = parts[1] if len(parts) > 1 and parts[1] != "-" else None
            isin_reinvest = parts[2] if len(parts) > 2 and parts[2] != "-" else None
            scheme_name = parts[3] if len(parts) > 3 else ""

            plan_type = None
            option_type = None

            if len(parts) >= 8:
                # 8-column layout
                plan_type = parts[4] or None
                option_type = parts[5] or None
                raw_nav = parts[6]
                raw_date = parts[7]
            elif len(parts) >= 6:
                # 6-column layout
                raw_nav = parts[4]
                raw_date = parts[5]
            else:
                continue

            try:
                nav = float(raw_nav)
            except (ValueError, TypeError):
                continue

            if nav <= 0:
                continue

            # Parse date (format: "06-Oct-2026")
            parsed_date = None
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    parsed_date = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue

            if not parsed_date:
                continue

            item = {
                "scheme_code": scheme_code,
                "isin": isin_growth,
                "name": scheme_name,
                "nav": nav,
                "date": parsed_date,
                "plan_type": plan_type,
                "option_type": option_type,
                "category": current_category,
                "amc": current_amc,
            }

            if scheme_code:
                by_code[scheme_code] = item
            if isin_growth:
                by_isin[isin_growth] = item
            if isin_reinvest:
                by_isin[isin_reinvest] = item

        except Exception:
            continue

    return by_code, by_isin


async def get_amfi_nav_data(force_refresh: bool = False) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """
    Retrieves and caches AMFI NAV file with retries and fallback URLs.
    """
    now = time.time()
    if not force_refresh and (now - _amfi_cache["timestamp"] < AMFI_CACHE_TTL_SECONDS) and _amfi_cache["data_by_code"]:
        return _amfi_cache["data_by_code"], _amfi_cache["data_by_isin"]

    urls = [AMFI_URL_PRIMARY, AMFI_URL_FALLBACK]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IPOPulse/1.0)"}

    text = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for url in urls:
            for attempt in range(2):
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200 and len(resp.text) > 1000:
                        text = resp.text
                        break
                except Exception as exc:
                    logger.warning("[MF NAV] Failed downloading AMFI NAV from %s (attempt %d): %s", url, attempt + 1, exc)
            if text:
                break

    if not text:
        logger.error("[MF NAV] Could not download AMFI daily NAV file from any mirror.")
        return _amfi_cache["data_by_code"], _amfi_cache["data_by_isin"]

    by_code, by_isin = parse_amfi_nav_text(text)
    if by_code:
        _amfi_cache["data_by_code"] = by_code
        _amfi_cache["data_by_isin"] = by_isin
        _amfi_cache["timestamp"] = now
        logger.info("[MF NAV] Successfully loaded AMFI daily NAVs for %d schemes", len(by_code))

    return by_code, by_isin


async def fetch_mfapi_scheme_history(scheme_code: str) -> Optional[dict]:
    """
    Fetches scheme history and metadata from mfapi.in as fallback or historical backfill.
    Returns {"meta": dict, "history": list[{"date": date, "nav": float}]} or None.
    """
    if not scheme_code:
        return None

    url = f"{MFAPI_BASE_URL}/{scheme_code}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IPOPulse/1.0)"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(2):
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    meta = data.get("meta", {})
                    raw_data = data.get("data", [])
                    history = []
                    for row in raw_data:
                        try:
                            row_date_str = row.get("date")
                            row_nav = float(row.get("nav", 0))
                            if row_nav <= 0 or not row_date_str:
                                continue
                            dt = datetime.strptime(row_date_str, "%d-%m-%Y").date()
                            history.append({"date": dt, "nav": row_nav})
                        except Exception:
                            continue
                    return {"meta": meta, "history": history}
            except Exception as exc:
                logger.warning("[MF NAV] mfapi.in request failed for %s (attempt %d): %s", scheme_code, attempt + 1, exc)

    return None


async def sync_all_scheme_navs(db: AsyncSession, force_refresh_amfi: bool = False) -> dict:
    """
    Updates NAVs for all tracked schemes in the database.
    - Appends to mf_nav_history.
    - On failure, keeps the last NAV and sets is_nav_stale = True (NEVER sets NAV to 0).
    """
    res = await db.execute(select(MFScheme))
    schemes = list(res.scalars().all())

    if not schemes:
        return {"updated": 0, "stale": 0, "errors": []}

    amfi_by_code, amfi_by_isin = await get_amfi_nav_data(force_refresh=force_refresh_amfi)

    updated_count = 0
    stale_count = 0
    errors: List[str] = []

    for scheme in schemes:
        nav_info = None

        # 1. Check AMFI file by scheme_code
        if scheme.scheme_code and scheme.scheme_code in amfi_by_code:
            nav_info = amfi_by_code[scheme.scheme_code]

        # 2. Check AMFI file by ISIN
        if not nav_info and scheme.isin and scheme.isin in amfi_by_isin:
            nav_info = amfi_by_isin[scheme.isin]

        # 3. If found in AMFI file
        if nav_info:
            nav_val = nav_info["nav"]
            nav_dt = nav_info["date"]

            scheme.latest_nav = nav_val
            scheme.latest_nav_date = nav_dt
            scheme.is_nav_stale = False

            # Fill missing metadata if available
            if not scheme.category and nav_info.get("category"):
                scheme.category = nav_info["category"]
            if not scheme.amc and nav_info.get("amc"):
                scheme.amc = nav_info["amc"]

            # Record in mf_nav_history if not already present
            existing_hist = await db.execute(
                select(MFNavHistory).where(
                    MFNavHistory.scheme_id == scheme.id,
                    MFNavHistory.date == nav_dt
                )
            )
            if not existing_hist.scalar_one_or_none():
                db.add(MFNavHistory(
                    scheme_id=scheme.id,
                    date=nav_dt,
                    nav=nav_val
                ))
            updated_count += 1
            continue

        # 4. Fallback: mfapi.in
        mfapi_data = None
        if scheme.scheme_code:
            try:
                mfapi_data = await fetch_mfapi_scheme_history(scheme.scheme_code)
            except Exception as e:
                errors.append(f"{scheme.name}: mfapi error: {e}")

        if mfapi_data and mfapi_data.get("history"):
            latest_entry = mfapi_data["history"][0]  # latest is index 0
            scheme.latest_nav = latest_entry["nav"]
            scheme.latest_nav_date = latest_entry["date"]
            scheme.is_nav_stale = False

            meta = mfapi_data.get("meta", {})
            if not scheme.category and meta.get("scheme_category"):
                scheme.category = meta["scheme_category"]
            if not scheme.amc and meta.get("fund_house"):
                scheme.amc = meta["fund_house"]

            # Ensure latest date in history
            existing_hist = await db.execute(
                select(MFNavHistory).where(
                    MFNavHistory.scheme_id == scheme.id,
                    MFNavHistory.date == latest_entry["date"]
                )
            )
            if not existing_hist.scalar_one_or_none():
                db.add(MFNavHistory(
                    scheme_id=scheme.id,
                    date=latest_entry["date"],
                    nav=latest_entry["nav"]
                ))
            updated_count += 1
            continue

        # 5. Both sources failed -> Keep last NAV, mark stale (NEVER default to 0)
        if scheme.latest_nav and scheme.latest_nav > 0:
            scheme.is_nav_stale = True
            stale_count += 1
            logger.warning("[MF NAV] Stale NAV retained for scheme '%s' (NAV: %.4f)", scheme.name, scheme.latest_nav)
        else:
            # Check if there is any historical entry in mf_nav_history
            hist_res = await db.execute(
                select(MFNavHistory).where(MFNavHistory.scheme_id == scheme.id)
                .order_by(MFNavHistory.date.desc()).limit(1)
            )
            latest_hist = hist_res.scalar_one_or_none()
            if latest_hist:
                scheme.latest_nav = latest_hist.nav
                scheme.latest_nav_date = latest_hist.date
                scheme.is_nav_stale = True
                stale_count += 1
            else:
                # Remains unpriced / None
                scheme.is_nav_stale = True
                errors.append(f"{scheme.name}: No NAV available from AMFI or mfapi.in")

    await db.commit()
    return {"updated": updated_count, "stale": stale_count, "errors": errors}


async def backfill_scheme_history_from_mfapi(db: AsyncSession, scheme_id: int, max_days: int = 365) -> int:
    """
    Backfills up to max_days of NAV history for a scheme using mfapi.in.
    Returns number of newly inserted history rows.
    """
    scheme = await db.get(MFScheme, scheme_id)
    if not scheme or not scheme.scheme_code:
        return 0

    data = await fetch_mfapi_scheme_history(scheme.scheme_code)
    if not data or not data.get("history"):
        return 0

    inserted = 0
    history = data["history"][:max_days]

    for item in history:
        entry_date = item["date"]
        entry_nav = item["nav"]

        exists = await db.execute(
            select(MFNavHistory.id).where(
                MFNavHistory.scheme_id == scheme_id,
                MFNavHistory.date == entry_date
            )
        )
        if not exists.scalar_one_or_none():
            db.add(MFNavHistory(
                scheme_id=scheme_id,
                date=entry_date,
                nav=entry_nav
            ))
            inserted += 1

    if inserted > 0:
        await db.commit()

    return inserted
