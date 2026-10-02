"""
Company facts service.
Fetches fundamentals, dividend history, valuation metrics, and IPO facts
via yfinance and local IPO database. Results are cached in-memory for 24 hours.
All missing fields return None, never silent default numbers.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.market_price_service import _clean_ticker, _yf_symbol

logger = logging.getLogger(__name__)

# In-memory TTL cache: cache_key -> (facts_dict, cached_at_datetime)
_facts_cache: dict[str, tuple[dict, datetime]] = {}
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def clear_facts_cache() -> None:
    """Clear in-memory facts cache (useful for testing)."""
    _facts_cache.clear()


def _fetch_yfinance_facts_sync(clean_sym: str) -> dict:
    """
    Blocking call to fetch company facts from yfinance.
    Always executed in an executor thread.
    Returns None for any field that is missing, never default numbers.
    """
    import yfinance as yf

    candidates = [f"{clean_sym}.NS", f"{clean_sym}.BO"]

    facts = {
        "symbol": clean_sym,
        "dividend_history": None,
        "dividend_yield": None,
        "trailing_pe": None,
        "eps": None,
        "market_cap": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "sector": None,
        "listing_date": None,
    }

    fetched_any = False

    for yf_ticker in candidates:
        try:
            ticker = yf.Ticker(yf_ticker)
            info = {}
            try:
                info = ticker.info or {}
            except Exception as e:
                logger.debug("Failed to get info for %s: %s", yf_ticker, e)

            # Dividends
            div_history = None
            try:
                divs = ticker.dividends
                if divs is not None and hasattr(divs, "empty"):
                    if divs.empty:
                        div_history = []
                    else:
                        tail5 = divs.tail(5)
                        div_history = []
                        for dt, val in tail5.items():
                            if val is not None:
                                try:
                                    dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                                    div_history.append({"date": dt_str, "amount": round(float(val), 2)})
                                except Exception:
                                    pass
            except Exception as e:
                logger.debug("Failed to get dividends for %s: %s", yf_ticker, e)

            # Check if this ticker gave valid data
            has_info = bool(info and any(info.get(k) is not None for k in ["trailingPE", "marketCap", "sector", "trailingEps"]))
            has_divs = div_history is not None

            if has_info or has_divs:
                fetched_any = True

                # Dividend history
                facts["dividend_history"] = div_history if div_history is not None else []

                # Dividend yield
                raw_yield = info.get("dividendYield")
                if raw_yield is not None:
                    try:
                        facts["dividend_yield"] = float(raw_yield)
                    except (ValueError, TypeError):
                        facts["dividend_yield"] = None

                # Trailing P/E
                raw_pe = info.get("trailingPE")
                if raw_pe is not None:
                    try:
                        facts["trailing_pe"] = float(raw_pe)
                    except (ValueError, TypeError):
                        facts["trailing_pe"] = None

                # EPS
                raw_eps = info.get("trailingEps")
                if raw_eps is not None:
                    try:
                        facts["eps"] = float(raw_eps)
                    except (ValueError, TypeError):
                        facts["eps"] = None

                # Market cap
                raw_mcap = info.get("marketCap")
                if raw_mcap is not None:
                    try:
                        facts["market_cap"] = float(raw_mcap)
                    except (ValueError, TypeError):
                        facts["market_cap"] = None

                # 52-week High/Low
                raw_high = info.get("fiftyTwoWeekHigh")
                if raw_high is not None:
                    try:
                        facts["fifty_two_week_high"] = float(raw_high)
                    except (ValueError, TypeError):
                        facts["fifty_two_week_high"] = None

                raw_low = info.get("fiftyTwoWeekLow")
                if raw_low is not None:
                    try:
                        facts["fifty_two_week_low"] = float(raw_low)
                    except (ValueError, TypeError):
                        facts["fifty_two_week_low"] = None

                # Sector
                raw_sector = info.get("sector")
                if raw_sector:
                    facts["sector"] = str(raw_sector).strip()

                # Listing date / First trade date
                first_ms = info.get("firstTradeDateMilliseconds")
                first_s = info.get("firstTradeDateEpochUtc")
                if first_ms:
                    try:
                        facts["listing_date"] = datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                    except Exception:
                        facts["listing_date"] = None
                elif first_s:
                    try:
                        facts["listing_date"] = datetime.fromtimestamp(first_s, tz=timezone.utc).strftime("%Y-%m-%d")
                    except Exception:
                        facts["listing_date"] = None

                # Successfully found data on this exchange suffix
                break
        except Exception as exc:
            logger.warning("[CompanyFacts] yfinance error for %s: %s", yf_ticker, exc)

    if not fetched_any:
        # Ticker completely failed in yfinance
        facts["dividend_history"] = None

    return facts


async def _fetch_ipo_data(
    db: AsyncSession,
    symbol: str,
    ipo_symbol: Optional[str] = None,
    current_price: Optional[float] = None
) -> dict:
    """Query local ipos table to merge IPO facts."""
    from app.models.ipo import IPO

    search_syms = [s.upper().strip() for s in [ipo_symbol, symbol] if s]
    if not search_syms:
        return {}

    try:
        stmt = (
            select(IPO)
            .where(IPO.symbol.in_(search_syms))
            .options(selectinload(IPO.gmp_records))
        )
        result = await db.execute(stmt)
        ipo_obj = result.scalars().first()
        if not ipo_obj:
            return {}

        issue_price = None
        if ipo_obj.issue_price is not None:
            issue_price = float(ipo_obj.issue_price)
        elif ipo_obj.price_band_high is not None:
            issue_price = float(ipo_obj.price_band_high)

        listing_date_str = ipo_obj.listing_date.strftime("%Y-%m-%d") if ipo_obj.listing_date else None

        # Listing gain calculation
        listing_gain_str = None
        if issue_price and current_price and issue_price > 0:
            diff = current_price - issue_price
            pct = round((diff / issue_price) * 100, 2)
            sign = "+" if diff >= 0 else ""
            listing_gain_str = f"{sign}{pct}% ({sign}₹{diff:.2f} vs issue ₹{issue_price:,.2f})"
        elif ipo_obj.gmp_records:
            latest_gmp = ipo_obj.gmp_records[0]
            if latest_gmp.gmp_percentage is not None:
                listing_gain_str = f"+{latest_gmp.gmp_percentage:.1f}% (+₹{latest_gmp.gmp_amount:.2f} GMP)"

        promoter_holding = None
        if ipo_obj.promoter_holding_post is not None:
            promoter_holding = float(ipo_obj.promoter_holding_post)
        elif ipo_obj.promoter_holding_pre is not None:
            promoter_holding = float(ipo_obj.promoter_holding_pre)

        return {
            "issue_price": issue_price,
            "listing_date": listing_date_str,
            "ipo_pe": float(ipo_obj.pe_ratio) if ipo_obj.pe_ratio is not None else None,
            "ronw": float(ipo_obj.ronw) if ipo_obj.ronw is not None else None,
            "promoter_holding": promoter_holding,
            "sector": ipo_obj.sector if ipo_obj.sector else None,
            "listing_gain": listing_gain_str,
            "ipo_type": ipo_obj.ipo_type.value if hasattr(ipo_obj.ipo_type, "value") else str(ipo_obj.ipo_type)
        }
    except Exception as exc:
        logger.warning("[CompanyFacts] Error fetching IPO data for %s: %s", symbol, exc)
        return {}


def get_company_facts_sync(
    symbol: str,
    ipo_symbol: Optional[str] = None,
    ipo_data: Optional[dict] = None,
    current_price: Optional[float] = None
) -> dict:
    """
    Synchronous facts fetcher (used by rule engine fallback and sync paths).
    Reads from 24-hour cache if present, otherwise calls yfinance synchronously.
    """
    clean_sym = _clean_ticker(symbol).upper()
    now = datetime.now(timezone.utc)

    if clean_sym in _facts_cache:
        cached_facts, cached_at = _facts_cache[clean_sym]
        if (now - cached_at).total_seconds() < _CACHE_TTL_SECONDS:
            res = dict(cached_facts)
            if ipo_data:
                _merge_ipo_data(res, ipo_data)
            return res

    facts = _fetch_yfinance_facts_sync(clean_sym)
    if ipo_data:
        _merge_ipo_data(facts, ipo_data)

    _facts_cache[clean_sym] = (dict(facts), now)
    return facts


async def get_company_facts(
    symbol: str,
    ipo_symbol: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    current_price: Optional[float] = None
) -> dict:
    """
    Primary async function to get company facts for a stock.
    1. Checks 24-hour in-memory cache.
    2. Runs yfinance in a threadpool executor.
    3. Merges IPO table data if ipo_symbol or db available.
    4. Returns dict with None for missing fields.
    """
    clean_sym = _clean_ticker(symbol).upper()
    now = datetime.now(timezone.utc)

    # Check cache
    if clean_sym in _facts_cache:
        cached_facts, cached_at = _facts_cache[clean_sym]
        if (now - cached_at).total_seconds() < _CACHE_TTL_SECONDS:
            return dict(cached_facts)

    # 1. Fetch yfinance in threadpool
    loop = asyncio.get_running_loop()
    facts = await loop.run_in_executor(None, _fetch_yfinance_facts_sync, clean_sym)

    # 2. Fetch and merge IPO data if available
    ipo_data = {}
    if db is not None:
        ipo_data = await _fetch_ipo_data(db, clean_sym, ipo_symbol=ipo_symbol, current_price=current_price)
    else:
        # Attempt to get a session if available
        try:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                ipo_data = await _fetch_ipo_data(session, clean_sym, ipo_symbol=ipo_symbol, current_price=current_price)
        except Exception as e:
            logger.debug("[CompanyFacts] Session unavailable for IPO lookup: %s", e)

    if ipo_data:
        _merge_ipo_data(facts, ipo_data)

    # 3. Store in 24h cache
    _facts_cache[clean_sym] = (dict(facts), now)
    return facts


def _merge_ipo_data(facts: dict, ipo_data: dict) -> None:
    """Merge IPO database record fields into facts dict."""
    if not ipo_data:
        return
    if ipo_data.get("issue_price") is not None:
        facts["issue_price"] = ipo_data["issue_price"]
    if ipo_data.get("listing_date") is not None and not facts.get("listing_date"):
        facts["listing_date"] = ipo_data["listing_date"]
    if ipo_data.get("ipo_pe") is not None:
        facts["ipo_pe"] = ipo_data["ipo_pe"]
    if ipo_data.get("ronw") is not None:
        facts["ronw"] = ipo_data["ronw"]
    if ipo_data.get("promoter_holding") is not None:
        facts["promoter_holding"] = ipo_data["promoter_holding"]
    if ipo_data.get("sector") is not None and not facts.get("sector"):
        facts["sector"] = ipo_data["sector"]
    if ipo_data.get("listing_gain") is not None:
        facts["listing_gain"] = ipo_data["listing_gain"]
    if ipo_data.get("ipo_type") is not None:
        facts["ipo_type"] = ipo_data["ipo_type"]


def format_company_facts_block(symbol: str, company_name: str, facts: dict) -> str:
    """Format company facts for AI context or rule engine with 'unavailable' for missing values."""
    sec = facts.get("sector") or "unavailable"
    mcap = facts.get("market_cap")
    mcap_str = f"₹{mcap:,.0f}" if mcap is not None else "unavailable"
    pe = facts.get("trailing_pe")
    pe_str = f"{pe:.2f}" if pe is not None else "unavailable"
    eps = facts.get("eps")
    eps_str = f"₹{eps:.2f}" if eps is not None else "unavailable"

    hi = facts.get("fifty_two_week_high")
    lo = facts.get("fifty_two_week_low")
    hi_str = f"₹{hi:,.2f}" if hi is not None else "unavailable"
    lo_str = f"₹{lo:,.2f}" if lo is not None else "unavailable"

    dy = facts.get("dividend_yield")
    if dy is not None:
        dy_str = f"{dy * 100:.2f}%" if dy <= 1.0 else f"{dy:.2f}%"
    else:
        dy_str = "unavailable"

    # Dividend history
    dh = facts.get("dividend_history")
    if dh is None:
        dh_str = "unavailable"
    elif len(dh) == 0:
        dh_str = "None recorded (No past dividend payments found in market data)"
    else:
        dh_str = ", ".join(f"{d['date']}: ₹{d['amount']:.2f}" for d in dh)

    ld = facts.get("listing_date") or "unavailable"

    lines = [
        f"### {symbol} ({company_name})",
        f"- Sector: {sec}",
        f"- Market Cap: {mcap_str}",
        f"- Trailing P/E: {pe_str}",
        f"- EPS: {eps_str}",
        f"- 52-Week Range: High {hi_str} / Low {lo_str}",
        f"- Dividend Yield: {dy_str}",
        f"- Dividend History (Last 5 Payments): {dh_str}",
        f"- Listing Date: {ld}"
    ]

    # Optional IPO details
    ipo_parts = []
    if facts.get("issue_price") is not None:
        ipo_parts.append(f"Issue Price: ₹{facts['issue_price']:,.2f}")
    if facts.get("ipo_pe") is not None:
        ipo_parts.append(f"IPO P/E: {facts['ipo_pe']:.1f}")
    if facts.get("ronw") is not None:
        ipo_parts.append(f"RoNW: {facts['ronw']:.1f}%")
    if facts.get("promoter_holding") is not None:
        ipo_parts.append(f"Promoter Holding: {facts['promoter_holding']:.1f}%")
    if facts.get("listing_gain") is not None:
        ipo_parts.append(f"Listing Gain vs Issue: {facts['listing_gain']}")
    if facts.get("ipo_type") is not None:
        ipo_parts.append(f"Segment: {facts['ipo_type']}")

    if ipo_parts:
        lines.append(f"- IPO Details: {' | '.join(ipo_parts)}")

    return "\n".join(lines)
