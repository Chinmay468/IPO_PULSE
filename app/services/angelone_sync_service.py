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
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import socket
import struct
import time
from typing import Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# Silence third-party SmartApi logs so sensitive credentials/tokens are never logged
for _log_name in ("SmartApi", "SmartApi.smartConnect", "smartapi"):
    logging.getLogger(_log_name).setLevel(logging.CRITICAL)


# ── IPv4 Enforcer ─────────────────────────────────────────────────────────────

@contextmanager
def force_ipv4():
    """Forces urllib3/requests to use IPv4 only during the block."""
    import urllib3.util.connection as urllib3_conn
    orig_allowed_gai_family = urllib3_conn.allowed_gai_family
    urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        urllib3_conn.allowed_gai_family = orig_allowed_gai_family


# ── Custom Error & Classification ─────────────────────────────────────────────

class AngelOneSyncError(RuntimeError):
    """Accurate, diagnosable Angel One sync error without leaking secrets."""
    def __init__(
        self,
        error_class: str,
        user_message: str,
        error_code: Optional[str] = None,
        step: str = "unknown"
    ):
        super().__init__(user_message)
        self.error_class = error_class
        self.user_message = user_message
        self.error_code = error_code
        self.step = step


# In-memory tracking of the last sync attempt
_last_sync_status = {
    "step": None,          # "connect", "login", "holdings"
    "error_class": None,   # "network_timeout", "ip_not_whitelisted", etc.
    "error_code": None,    # e.g. "AB1004"
    "timestamp": None,
    "success": None,
}


def record_sync_failure(step: str, error_class: str, error_code: Optional[str] = None) -> None:
    _last_sync_status["step"] = step
    _last_sync_status["error_class"] = error_class
    _last_sync_status["error_code"] = error_code
    _last_sync_status["timestamp"] = datetime.now(timezone.utc)
    _last_sync_status["success"] = False


def record_sync_success() -> None:
    _last_sync_status["step"] = None
    _last_sync_status["error_class"] = None
    _last_sync_status["error_code"] = None
    _last_sync_status["timestamp"] = datetime.now(timezone.utc)
    _last_sync_status["success"] = True


def get_last_sync_status() -> dict:
    return _last_sync_status.copy()


def classify_error(
    exc: Optional[Exception] = None,
    response_dict: Optional[dict] = None,
    http_status: Optional[int] = None,
    step: str = "unknown"
) -> Tuple[str, str, Optional[str]]:
    """
    Classifies failure into:
      - network_timeout
      - ip_not_whitelisted
      - invalid_credentials_mpin
      - invalid_totp
      - rate_limited
      - unknown
    Returns: (error_class, user_message, sanitized_error_code)
    """
    msg = ""
    error_code = None

    if response_dict and isinstance(response_dict, dict):
        msg = str(response_dict.get("message") or "")
        error_code = (
            response_dict.get("errorcode") or
            response_dict.get("errorCode") or
            response_dict.get("code") or
            None
        )
    if exc:
        msg = f"{msg} {exc}".strip()
        if not error_code and hasattr(exc, "code"):
            error_code = str(getattr(exc, "code"))

    msg_lower = msg.lower()
    code_str = str(error_code).upper() if error_code else ""

    # 1. Network / Timeout
    if (
        isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout, TimeoutError)) or
        "timed out" in msg_lower or
        "timeout" in msg_lower or
        "connection refused" in msg_lower or
        "connection reset" in msg_lower or
        "failed to establish a new connection" in msg_lower or
        "connection error" in msg_lower or
        "httpsconnectionpool" in msg_lower or
        "max retries exceeded" in msg_lower or
        "network is unreachable" in msg_lower or
        "nameresolutionerror" in msg_lower
    ):
        return (
            "network_timeout",
            "Connection to Angel One SmartAPI timed out or network failed. Please verify internet connectivity and retry.",
            error_code or "NETWORK_TIMEOUT"
        )

    # 2. Rate Limited
    if (
        http_status == 429 or
        code_str in ("AB1009", "AB1010", "AG8005") or
        "rate limit" in msg_lower or
        "too many requests" in msg_lower or
        "access frequency" in msg_lower or
        "throttled" in msg_lower
    ):
        return (
            "rate_limited",
            "Angel One SmartAPI rate limit exceeded. Please wait a few moments before trying again.",
            error_code or "RATE_LIMIT"
        )

    # 3. IP Not Whitelisted
    if (
        code_str in ("AB1007", "AB1008") or
        ("ip" in msg_lower and any(w in msg_lower for w in ("whitelist", "not allowed", "not registered", "not authorized", "invalid ip", "restricted")))
    ):
        return (
            "ip_not_whitelisted",
            "Your server's egress IP address is not whitelisted in the Angel One SmartAPI developer portal. Please add your server's IPv4 address to the whitelist in your SmartAPI app settings at smartapi.angelone.in.",
            error_code or "IP_NOT_WHITELISTED"
        )

    # 4. Invalid or Expired TOTP
    if (
        code_str in ("AB1050", "AB1051", "AB1052", "AB2001", "AG8004") or
        any(w in msg_lower for w in ("totp", "2fa", "time based otp", "otp is invalid", "otp expired", "otp is expired"))
    ):
        return (
            "invalid_totp",
            "Authentication failed: Invalid or expired TOTP. Please verify your TOTP secret key or ensure your server clock is synchronized with NTP.",
            error_code or "INVALID_TOTP"
        )

    # 5. Invalid Credentials / MPIN
    if (
        code_str in ("AB1001", "AB1002", "AB1004", "AG8001", "AG8002", "AG8003") or
        http_status == 401 or
        any(w in msg_lower for w in ("invalid password", "invalid mpin", "invalid client", "user not found", "invalid user", "invalid credentials", "client is inactive", "password/mpin", "pin is invalid", "unauthorized"))
    ):
        return (
            "invalid_credentials_mpin",
            "Authentication failed: Invalid Angel One Client ID, API key, or MPIN. Please verify your credentials in configuration.",
            error_code or "INVALID_CREDENTIALS"
        )

    # 6. Unknown / Unclassified
    return (
        "unknown",
        f"Angel One SmartAPI error: {error_code or 'UNKNOWN'}. Please check your account status or contact support.",
        error_code or "UNKNOWN"
    )


def _is_configured() -> bool:
    """Return True if Angel One credentials are set in env."""
    from app.config import settings
    return bool(
        getattr(settings, "ANGELONE_API_KEY", None) and
        getattr(settings, "ANGELONE_CLIENT_ID", None) and
        getattr(settings, "ANGELONE_PASSWORD", None)
    )


# ── Diagnosis Helpers ─────────────────────────────────────────────────────────

def get_egress_ipv4(timeout: float = 3.0) -> Optional[str]:
    """Retrieves server's public egress IPv4 address via external IP echo service."""
    urls = [
        "https://api4.ipify.org?format=json",
        "https://ipv4.icanhazip.com",
    ]
    for url in urls:
        try:
            with force_ipv4():
                resp = requests.get(url, timeout=timeout)
                if resp.ok:
                    if "json" in resp.headers.get("Content-Type", ""):
                        return resp.json().get("ip", "").strip() or None
                    return resp.text.strip() or None
        except Exception:
            continue
    return None


def get_egress_ipv6(timeout: float = 2.0) -> Optional[str]:
    """Retrieves server's public egress IPv6 address if available, else None."""
    urls = [
        "https://api6.ipify.org?format=json",
        "https://ipv6.icanhazip.com",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.ok:
                if "json" in resp.headers.get("Content-Type", ""):
                    return resp.json().get("ip", "").strip() or None
                return resp.text.strip() or None
        except Exception:
            continue
    return None


def get_time_offset(host: str = "pool.ntp.org", timeout: float = 2.0) -> Tuple[Optional[float], bool]:
    """
    Measures system time offset (seconds) vs an NTP server.
    Falls back to HTTP Date header if UDP port 123 is blocked.
    Returns (offset_seconds, is_synced_ok).
    """
    # 1. Primary: UDP NTP
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(timeout)
        data = b'\x1b' + 47 * b'\0'
        t1 = time.time()
        client.sendto(data, (host, 123))
        recv_data, _ = client.recvfrom(1024)
        t4 = time.time()
        if recv_data and len(recv_data) >= 48:
            unpacked = struct.unpack('!12I', recv_data[0:48])
            NTP_DELTA = 2208988800
            t3 = unpacked[10] + float(unpacked[11]) / 2**32 - NTP_DELTA
            offset = t3 - ((t1 + t4) / 2.0)
            rounded = round(offset, 3)
            return rounded, abs(rounded) <= 5.0
    except Exception:
        pass

    # 2. Fallback: HTTP Date Header
    try:
        t0 = time.time()
        r = requests.head("https://www.google.com", timeout=timeout)
        t1 = time.time()
        date_hdr = r.headers.get("Date")
        if date_hdr:
            remote_time = parsedate_to_datetime(date_hdr).timestamp()
            local_time = (t0 + t1) / 2.0
            offset = remote_time - local_time
            rounded = round(offset, 3)
            return rounded, abs(rounded) <= 5.0
    except Exception:
        pass

    return None, False


def get_env_status() -> dict:
    """Returns boolean presence flags for required environment variables (never values)."""
    from app.config import settings
    return {
        "api_key_set": bool(getattr(settings, "ANGELONE_API_KEY", None)),
        "client_id_set": bool(getattr(settings, "ANGELONE_CLIENT_ID", None)),
        "password_set": bool(getattr(settings, "ANGELONE_PASSWORD", None)),
        "totp_secret_set": bool(getattr(settings, "ANGELONE_TOTP_SECRET", None)),
    }


async def diagnose_angelone() -> dict:
    """
    Runs diagnostic probes asynchronously in threadpool:
    - Egress IPv4 & IPv6
    - NTP/HTTP time offset
    - Presence of env variables
    - Last sync failure information
    """
    loop = asyncio.get_event_loop()
    ipv4 = await loop.run_in_executor(None, get_egress_ipv4)
    ipv6 = await loop.run_in_executor(None, get_egress_ipv6)
    offset, ntp_ok = await loop.run_in_executor(None, get_time_offset)
    env_vars = get_env_status()
    last_failure = get_last_sync_status()

    return {
        "egress_ipv4": ipv4,
        "egress_ipv6": ipv6,
        "time_offset_seconds": offset,
        "ntp_sync_ok": ntp_ok,
        "env_vars": env_vars,
        "last_failure": last_failure,
    }


# ── Holdings Fetch Implementation ─────────────────────────────────────────────

def _fetch_holdings_sync() -> list[dict]:
    """
    Blocking call — runs in executor.
    Forces IPv4 for all HTTP requests to Angel One.
    Classifies errors cleanly and logs sanitized error class and error code only.
    """
    from app.config import settings

    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError as exc:
        err_class = "unknown"
        code = "IMPORT_ERROR"
        record_sync_failure("connect", err_class, code)
        logger.error("[AngelOne Sync] connect failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(
            err_class,
            "smartapi-python dependency import error. Add required packages and rebuild.",
            code,
            step="connect"
        )

    api_key = settings.ANGELONE_API_KEY
    client_id = settings.ANGELONE_CLIENT_ID
    password = settings.ANGELONE_PASSWORD
    totp_secret = getattr(settings, "ANGELONE_TOTP_SECRET", None)

    # 1. Connect / Initialize step
    try:
        with force_ipv4():
            obj = SmartConnect(api_key=api_key)
    except Exception as exc:
        err_class, user_msg, code = classify_error(exc=exc, step="connect")
        record_sync_failure("connect", err_class, code)
        logger.error("[AngelOne Sync] connect failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(err_class, user_msg, code, step="connect")

    # 2. Login step
    try:
        totp = pyotp.TOTP(totp_secret).now() if totp_secret else ""
        with force_ipv4():
            session = obj.generateSession(client_id, password, totp)
    except Exception as exc:
        err_class, user_msg, code = classify_error(exc=exc, step="login")
        record_sync_failure("login", err_class, code)
        logger.error("[AngelOne Sync] login failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(err_class, user_msg, code, step="login")

    if not isinstance(session, dict) or not session.get("status"):
        err_class, user_msg, code = classify_error(response_dict=session, step="login")
        record_sync_failure("login", err_class, code)
        logger.error("[AngelOne Sync] login failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(err_class, user_msg, code, step="login")

    # 3. Holdings fetch step
    try:
        if not getattr(obj, "access_token", None):
            jwt = session.get("data", {}).get("jwtToken", "")
            if jwt.startswith("Bearer "):
                jwt = jwt[7:]
            obj.setAccessToken(jwt)

        with force_ipv4():
            resp = obj.holding()
    except Exception as exc:
        err_class, user_msg, code = classify_error(exc=exc, step="holdings")
        record_sync_failure("holdings", err_class, code)
        logger.error("[AngelOne Sync] holdings failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(err_class, user_msg, code, step="holdings")

    if not isinstance(resp, dict) or not resp.get("status"):
        err_class, user_msg, code = classify_error(response_dict=resp, step="holdings")
        record_sync_failure("holdings", err_class, code)
        logger.error("[AngelOne Sync] holdings failed: error_class=%s, error_code=%s", err_class, code)
        raise AngelOneSyncError(err_class, user_msg, code, step="holdings")

    # Successful sync
    record_sync_success()

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
            "company_name": h.get("tradingsymbol", sym),
            "quantity": qty,
            "avg_buy_price": price,
        })
    return out


async def fetch_angelone_holdings() -> list[dict]:
    """
    Async wrapper. Returns list of holding dicts, or raises AngelOneSyncError.
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
        raise AngelOneSyncError(
            "unknown",
            "Angel One credentials not configured. Set ANGELONE_API_KEY, ANGELONE_CLIENT_ID, ANGELONE_PASSWORD in your .env file.",
            error_code="NOT_CONFIGURED",
            step="connect"
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
            logger.warning("[AngelOne Sync] Failed for %s: %s", h['symbol'], exc)

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}
