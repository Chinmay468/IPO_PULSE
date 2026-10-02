"""
Live market price fetcher using yfinance.
NSE symbols must be suffixed with .NS (e.g. TATATECH.NS)
BSE symbols must be suffixed with .BO
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory TTL cache: symbol -> (price, day_change_pct, fetched_at)
_price_cache: dict[str, tuple[float, float, datetime]] = {}
_CACHE_TTL_SECONDS = 180  # 3-minute cache to avoid rate limits


# Known company name / broker trading symbol to standard NSE/BSE ticker mapping
_SYMBOL_ALIASES: dict[str, str] = {
    "ASHOK LEYLAND": "ASHOKLEY",
    "ASHOKLEYLAND": "ASHOKLEY",
    "BHANSALI ENGG.": "BEPL",
    "BHANSALI ENGG": "BEPL",
    "BHANSALI ENGINEERING": "BEPL",
    "BEPL": "BEPL",
    "PRAJ INDUSTRIES": "PRAJIND",
    "PRAJIND": "PRAJIND",
    "TATA MOTORS": "TATAMOTORS",
    "TATAMOTORS": "TATAMOTORS",
    "TATA POWER": "TATAPOWER",
    "TATAPOWER": "TATAPOWER",
    "TATA STEEL": "TATASTEEL",
    "TATASTEEL": "TATASTEEL",
    "RELIANCE IND": "RELIANCE",
    "RELIANCE INDUSTRIES": "RELIANCE",
    "STATE BANK OF INDIA": "SBIN",
    "SBI": "SBIN",
    "HDFC BANK": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
    "L&T": "LT",
    "LARSEN & TOUBRO": "LT",
    "MAHINDRA & MAHINDRA": "M&M",
    "BAJAJ FINANCE": "BAJFINANCE",
    "BAJAJ FINSERV": "BAJAJFINSV",
    "KOTAK MAHINDRA BANK": "KOTAKBANK",
    "KOTAK BANK": "KOTAKBANK",
    "INFOSYS": "INFY",
    "BHARTI AIRTEL": "BHARTIARTL",
    "ASIAN PAINTS": "ASIANPAINT",
    "MARUTI SUZUKI": "MARUTI",
    "TITAN COMPANY": "TITAN",
    "ULTRATECH CEMENT": "ULTRACEMCO",
    "SUN PHARMA": "SUNPHARMA",
    "NESTLE INDIA": "NESTLEIND",
    "COAL INDIA": "COALINDIA",
    "POWER GRID": "POWERGRID",
    "INDIAN OIL": "IOC",
    "JSW STEEL": "JSWSTEEL",
    "ADANI ENTERPRISES": "ADANIENT",
    "ADANI PORTS": "ADANIPORTS",
    "ADANI GREEN": "ADANIGREEN",
    "ADANI POWER": "ADANIPOWER",
    "PAYTM": "PAYTM",
    "ONE97": "PAYTM",
    "JIO FINANCIAL": "JIOFIN",
    "HINDUSTAN AERONAUTICS": "HAL",
    "BHARAT ELECTRONICS": "BEL",
    "BHARAT HEAVY ELECTRICALS": "BHEL",
    "VEDANTA": "VEDL",
    "VARUN BEVERAGES": "VBL",
}


def _clean_ticker(symbol: str) -> str:
    sym = symbol.upper().strip()
    # Strip common suffixes
    for suffix in ("-EQ", "-BE", "-N1", ".NS", ".BO", " EQ", " BE"):
        if sym.endswith(suffix):
            sym = sym[:-len(suffix)].strip()
    # Check direct alias match
    if sym in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[sym]
    # Check normalized alias match
    norm = sym.replace(".", "").replace(" ", "").replace("&", "").replace("-", "")
    if norm in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[norm]
    for k, v in _SYMBOL_ALIASES.items():
        if k.replace(".", "").replace(" ", "").replace("&", "").replace("-", "") == norm:
            return v
    return norm or sym


def _yf_symbol(symbol: str, exchange: str) -> str:
    clean_sym = _clean_ticker(symbol)
    if exchange == "NSE":
        return f"{clean_sym}.NS"
    elif exchange == "BSE":
        return f"{clean_sym}.BO"
    return clean_sym



def _is_cached(symbol: str) -> bool:
    if symbol not in _price_cache:
        return False
    _, _, fetched_at = _price_cache[symbol]
    return (datetime.utcnow() - fetched_at).total_seconds() < _CACHE_TTL_SECONDS


async def get_live_price(symbol: str, exchange: str = "NSE") -> tuple[Optional[float], Optional[float]]:
    """
    Returns (live_price, day_change_pct) for the given symbol.
    Falls back to (None, None) on any error so the app never crashes.
    """
    yf_sym = _yf_symbol(symbol, exchange)

    if _is_cached(yf_sym):
        price, change_pct, _ = _price_cache[yf_sym]
        return price, change_pct

    try:
        # Run blocking yfinance call in threadpool
        price, change_pct = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_yf, yf_sym
        )
        if price is not None:
            _price_cache[yf_sym] = (price, change_pct or 0.0, datetime.utcnow())
        return price, change_pct
    except Exception as exc:
        logger.warning(f"[MarketPrice] Failed to fetch {yf_sym}: {exc}")
        return None, None


def _fetch_yf(yf_sym: str) -> tuple[Optional[float], Optional[float]]:
    """Blocking yfinance fetch — always run in executor."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_sym)
        info = ticker.fast_info
        price = float(info.last_price) if info.last_price else None
        prev_close = float(info.previous_close) if info.previous_close else None
        if price and prev_close and prev_close > 0:
            day_change_pct = round(((price - prev_close) / prev_close) * 100, 2)
        else:
            day_change_pct = 0.0
        return price, day_change_pct
    except Exception as exc:
        logger.debug(f"[MarketPrice] yf inner error for {yf_sym}: {exc}")
        return None, None


async def get_live_prices_bulk(symbols_exchanges: list[tuple[str, str]]) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Fetch prices for multiple holdings concurrently."""
    tasks = [get_live_price(sym, exch) for sym, exch in symbols_exchanges]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for (sym, exch), result in zip(symbols_exchanges, results):
        yf_sym = _yf_symbol(sym, exch)
        if isinstance(result, Exception):
            out[yf_sym] = (None, None)
        else:
            out[yf_sym] = result  # type: ignore
    return out


def invalidate_cache(symbol: str = None):
    """Clear cache for a symbol or entirely."""
    if symbol:
        _price_cache.pop(symbol, None)
    else:
        _price_cache.clear()
