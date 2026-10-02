"""
Angel One SmartAPI integration for fetching live portfolio holdings.

Required environment variables (optional):
  - ANGELONE_API_KEY
  - ANGELONE_CLIENT_ID
  - ANGELONE_PASSWORD (4-digit MPIN)
  - ANGELONE_TOTP_SECRET (base32 secret from authenticator QR code)

All fields are optional — if not set, Angel One sync is disabled gracefully.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """Return True if Angel One credentials are set in env."""
    from app.config import settings
    return bool(
        getattr(settings, "ANGELONE_API_KEY", None) and
        getattr(settings, "ANGELONE_CLIENT_ID", None) and
        getattr(settings, "ANGELONE_PASSWORD", None)
    )


def _fetch_holdings_sync() -> list[dict]:
    """
    Blocking call — run in executor.
    Returns list of dicts with keys:
      symbol, exchange, company_name, quantity, avg_buy_price
    """
    from app.config import settings

    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError as exc:
        raise RuntimeError(
            f"smartapi-python dependency import error: {exc}. "
            "Add required packages to requirements.txt and rebuild."
        )

    api_key    = settings.ANGELONE_API_KEY
    client_id  = settings.ANGELONE_CLIENT_ID
    password   = settings.ANGELONE_PASSWORD
    totp_secret = getattr(settings, "ANGELONE_TOTP_SECRET", None)

    obj = SmartConnect(api_key=api_key)

    # Generate TOTP if secret is available, else use empty string
    totp = pyotp.TOTP(totp_secret).now() if totp_secret else ""

    session = obj.generateSession(client_id, password, totp)
    if not session.get("status"):
        raise RuntimeError(f"Angel One login failed: {session.get('message')}")

    # SmartConnect.generateSession already calls setAccessToken with the raw JWT internally.
    # session["data"]["jwtToken"] has a "Bearer " prefix attached; passing it to
    # obj.setAccessToken causes SmartConnect._request to send "Bearer Bearer ...",
    # which Angel One rejects with 'Invalid Token'.
    if not getattr(obj, "access_token", None):
        jwt = session.get("data", {}).get("jwtToken", "")
        if jwt.startswith("Bearer "):
            jwt = jwt[7:]
        obj.setAccessToken(jwt)

    resp = obj.holding()
    if not resp.get("status"):
        raise RuntimeError(f"Holdings fetch failed: {resp.get('message')}")

    raw: list[dict] = resp.get("data", []) or []
    out = []
    for h in raw:
        sym = h.get("tradingsymbol", "").replace("-EQ", "").replace("-BE", "").strip()
        if not sym:
            continue

        raw_qty = h.get("quantity")
        raw_price = h.get("averageprice")

        try:
            qty = float(raw_qty) if raw_qty is not None else 0.0
        except (ValueError, TypeError):
            qty = 0.0

        try:
            price = float(raw_price) if raw_price is not None else 0.0
        except (ValueError, TypeError):
            price = 0.0

        if qty <= 0 or price <= 0:
            logger.warning(
                "[AngelOne Sync] Skipping holding %s: null/zero quantity (%s) or average price (%s)",
                sym, raw_qty, raw_price
            )
            continue

        out.append({
            "symbol": sym,
            "exchange": h.get("exchange", "NSE"),
            "company_name": h.get("tradingsymbol", sym),  # SmartAPI doesn't return full name
            "quantity": qty,
            "avg_buy_price": price,
        })
    return out


async def fetch_angelone_holdings() -> list[dict]:
    """
    Async wrapper. Returns list of holding dicts, or raises RuntimeError.
    Never call this if _is_configured() returns False.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_holdings_sync)


async def sync_angelone_to_portfolio(db) -> dict:
    """
    Pull Angel One holdings and upsert into local portfolio.
    - Creates new holdings that don't exist yet.
    - Updates quantity + avg_price for existing ones.
    Returns summary dict: {created, updated, skipped, errors}
    """
    from app.services import portfolio_service as svc
    from app.schemas.portfolio import HoldingCreate, HoldingUpdate
    from app.models.portfolio import Exchange

    if not _is_configured():
        raise RuntimeError(
            "Angel One credentials not configured. "
            "Set ANGELONE_API_KEY, ANGELONE_CLIENT_ID, ANGELONE_PASSWORD in your .env file."
        )

    holdings = await fetch_angelone_holdings()
    created = updated = skipped = 0
    errors = []

    for h in holdings:
        if h["quantity"] <= 0 or h.get("avg_buy_price", 0) <= 0:
            skipped += 1
            continue
        try:
            exchange = h["exchange"] if h["exchange"] in ("NSE", "BSE") else "NSE"
            existing = await svc.get_holding_by_symbol(db, h["symbol"], exchange)
            if existing:
                await svc.update_holding(db, existing.id, HoldingUpdate(
                    quantity=h["quantity"],
                    avg_buy_price=h["avg_buy_price"],
                ))
                updated += 1
            else:
                await svc.create_holding(db, HoldingCreate(
                    symbol=h["symbol"],
                    company_name=h["company_name"],
                    exchange=Exchange(exchange),
                    quantity=h["quantity"],
                    avg_buy_price=h["avg_buy_price"],
                ))
                created += 1
        except Exception as exc:
            errors.append(f"{h['symbol']}: {exc}")
            logger.warning(f"[AngelOne Sync] Failed for {h['symbol']}: {exc}")

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}
