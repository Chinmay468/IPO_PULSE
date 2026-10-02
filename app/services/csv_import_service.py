"""
Universal portfolio import parser supporting Excel (.xlsx, .xls), HTML tables, and CSV/TSV files
exported from Angel One, Zerodha, Groww, Upstox, ICICI Direct, HDFC Sky, and generic templates.
"""
import io
import re
import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Excluded tokens that indicate summary/aggregate tables rather than stock holdings
_EXCLUDE_HEADER_TOKENS = {
    "type of holdings", "no of scrips", "scrips/funds", "funds/bonds",
    "portfolio summary", "asset allocation", "category summary", "summary of investment"
}

# Column aliases ordered by preference
_SYMBOL_COLS = [
    "symbol", "tradingsymbol", "scrip name", "stock symbol", "company name",
    "scrip", "stock", "instrument", "security name", "security", "particulars",
    "ticker", "company", "description", "scrip description", "isin", "isin code"
]

_QTY_COLS = [
    "quantity", "qty", "net qty", "net quantity", "available qty", "available quantity",
    "holding quantity", "closing qty", "closingqty", "total qty", "total quantity",
    "holdings", "shares", "units", "current balance", "balance qty", "free qty", "dp qty"
]

_BUY_PRICE_COLS = [
    # Angel One export header (must be first — most specific)
    "avg trading price", "average trading price",
    # Generic broker headers
    "average price", "avg price", "average buy price", "avg buy price", "avg cost",
    "buy price", "purchase price", "cost price", "buy avg", "cost rate", "avg rate",
    "cost price per unit", "purchaseprice", "averageprice", "avg cost price", "average cost",
    "avg price rs", "buy avg price", "buy rate"
]

_FALLBACK_PRICE_COLS = ["ltp", "market price", "current price", "last price", "price", "rate", "cost"]

_EXCHANGE_COLS = ["exchange", "exch", "market", "segment", "mkt"]

_NAME_COLS = [
    "company name", "company", "instrument name", "stock name", "scrip name",
    "description", "security description", "particulars", "security", "name"
]


def _norm(s: str) -> str:
    """Normalize string by lowercasing, replacing punctuation with spaces, and collapsing whitespace."""
    cleaned = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _find_col_ordered(headers: list[str], candidate_list: list[str], exclude: set[str] = _EXCLUDE_HEADER_TOKENS) -> Optional[int]:
    """Find column index matching candidates in order of preference."""
    # 1. Exact match in order of preference
    for cand in candidate_list:
        for i, h in enumerate(headers):
            n = _norm(h)
            if any(exc in n for exc in exclude):
                continue
            if n == cand:
                return i

    # 2. Substring match in order of preference
    for cand in candidate_list:
        for i, h in enumerate(headers):
            n = _norm(h)
            if any(exc in n for exc in exclude):
                continue
            if cand in n and len(n) <= len(cand) + 15:
                return i
    return None


def _clean_symbol(raw: str) -> str:
    """Strip exchange suffixes and cleanup symbols."""
    sym = str(raw).strip().upper()
    for suffix in ("-EQ", "-BE", "-N1", ".NS", ".BO", " EQ", " BE"):
        if sym.endswith(suffix):
            sym = sym[: -len(suffix)].strip()
    return sym


def _parse_float(val) -> float:
    if val is None:
        return 0.0
    s = str(val).replace(",", "").replace("₹", "").replace("INR", "").replace("$", "").strip()
    try:
        return float(s or 0)
    except ValueError:
        return 0.0


def parse_rows(rows: list[list[str]], skipped_out: Optional[list[dict]] = None) -> list[dict]:
    """
    Parse a 2D grid of string cells into structured stock holdings.
    Scans for multiple tables/sections (e.g. skips summary cards and extracts equity tables).
    """
    results = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if not row or not any(str(c).strip() for c in row):
            i += 1
            continue

        sym_col = _find_col_ordered(row, _SYMBOL_COLS)
        qty_col = _find_col_ordered(row, _QTY_COLS)

        if sym_col is not None and qty_col is not None and sym_col != qty_col:
            headers = [str(c).strip() for c in row]
            price_col = _find_col_ordered(headers, _BUY_PRICE_COLS)
            if price_col is None:
                price_col = _find_col_ordered(headers, _FALLBACK_PRICE_COLS)
            exch_col = _find_col_ordered(headers, _EXCHANGE_COLS)
            name_col = _find_col_ordered(headers, _NAME_COLS)

            if sym_col == name_col:
                name_cand = _find_col_ordered(headers, ["company name", "company", "description", "security name"])
                if name_cand is not None and name_cand != sym_col:
                    name_col = name_cand

            j = i + 1
            while j < len(rows):
                data_row = rows[j]
                if not data_row or not any(str(c).strip() for c in data_row):
                    j += 1
                    continue

                # Check if this row is another table header
                sub_sym = _find_col_ordered(data_row, _SYMBOL_COLS)
                sub_qty = _find_col_ordered(data_row, _QTY_COLS)
                if sub_sym is not None and sub_qty is not None and sub_sym != sub_qty:
                    break

                try:
                    if sym_col >= len(data_row) or qty_col >= len(data_row):
                        j += 1
                        continue

                    raw_sym = str(data_row[sym_col]).strip()
                    # Skip summary / total / blank rows
                    if not raw_sym or any(raw_sym.lower().startswith(tok) for tok in (
                        "total", "grand total", "sub total", "portfolio", "nan", "none",
                        "null", "type of", "asset allocation", "category", "disclaimer"
                    )):
                        j += 1
                        continue

                    sym = _clean_symbol(raw_sym)
                    if not sym:
                        j += 1
                        continue

                    qty = _parse_float(data_row[qty_col])
                    price = _parse_float(data_row[price_col]) if (price_col is not None and price_col < len(data_row)) else None

                    if qty <= 0:
                        if skipped_out is not None:
                            skipped_out.append({"symbol": sym, "reason": "missing or zero quantity"})
                        j += 1
                        continue

                    if price is None or price <= 0:
                        if skipped_out is not None:
                            skipped_out.append({"symbol": sym, "reason": "missing or zero buy price"})
                        j += 1
                        continue

                    exchange = "NSE"
                    if exch_col is not None and exch_col < len(data_row):
                        raw_exch = str(data_row[exch_col]).strip().upper()
                        if "BSE" in raw_exch:
                            exchange = "BSE"

                    name = sym
                    if name_col is not None and name_col < len(data_row):
                        cand_name = str(data_row[name_col]).strip()
                        if cand_name and cand_name.lower() not in ("nan", "none", "null"):
                            name = cand_name

                    results.append({
                        "symbol": sym,
                        "exchange": exchange,
                        "company_name": name,
                        "quantity": qty,
                        "avg_buy_price": price,
                    })
                except Exception as exc:
                    logger.debug(f"[Import Parser] Skipping row {j}: {exc}")
                j += 1
            i = j
        else:
            i += 1

    return results


def parse_file(content: bytes, filename: str, password: Optional[str] = None, skipped_out: Optional[list[dict]] = None) -> list[dict]:
    """
    Universal multi-format parser powered by Pandas & msoffcrypto.
    Automatically handles password-protected files, multi-sheet Excel, binary .xls, .xlsx, HTML tables, and CSVs.
    """
    # 0. Check if file is password-protected by broker
    try:
        import msoffcrypto
        office_file = msoffcrypto.OfficeFile(io.BytesIO(content))
        if office_file.is_encrypted():
            from app.config import settings
            trial_passwords = []
            if password:
                trial_passwords.extend([password.strip(), password.strip().upper(), password.strip().lower()])
            if getattr(settings, "ANGELONE_PAN", None):
                pan = settings.ANGELONE_PAN.strip()
                trial_passwords.extend([pan, pan.upper(), pan.lower()])
            if getattr(settings, "ANGELONE_CLIENT_ID", None):
                cid = settings.ANGELONE_CLIENT_ID.strip()
                trial_passwords.extend([cid, cid.upper(), cid.lower()])
            if getattr(settings, "ANGELONE_PASSWORD", None):
                trial_passwords.append(settings.ANGELONE_PASSWORD.strip())

            decrypted_bytes = None
            for pwd in trial_passwords:
                if not pwd:
                    continue
                try:
                    dec = io.BytesIO()
                    office_file.load_key(password=pwd)
                    office_file.decrypt(dec)
                    decrypted_bytes = dec.getvalue()
                    logger.info(f"Successfully decrypted password-protected Excel workbook with key '{pwd[:2]}***'.")
                    break
                except Exception:
                    continue

            if decrypted_bytes is not None:
                content = decrypted_bytes
            else:
                raise ValueError(
                    "This file is password-protected by Angel One (usually your PAN number in CAPITAL letters e.g. ABCDE1234F). "
                    "Please provide your PAN password or open the file in Excel and save as unencrypted .xlsx/.csv."
                )
    except ValueError:
        raise
    except Exception as e_crypto:
        logger.debug(f"msoffcrypto check: {e_crypto}")

    holdings = []

    # 1. Try reading all sheets via Pandas Excel engine (openpyxl / xlrd)
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
        if isinstance(sheets, dict):
            for sheet_name, df_sheet in sheets.items():
                if not df_sheet.empty:
                    rows = df_sheet.fillna("").astype(str).values.tolist()
                    holdings.extend(parse_rows(rows, skipped_out=skipped_out))
        elif isinstance(sheets, pd.DataFrame) and not sheets.empty:
            rows = sheets.fillna("").astype(str).values.tolist()
            holdings.extend(parse_rows(rows, skipped_out=skipped_out))
    except Exception as e_excel:
        logger.debug(f"pd.read_excel failed: {e_excel}")

    # 2. Try reading as HTML table (Angel One / Zerodha often export HTML disguised as .xls/.xlsx)
    if not holdings:
        try:
            tables = pd.read_html(io.BytesIO(content))
            for tbl in tables:
                if not tbl.empty:
                    rows = tbl.fillna("").astype(str).values.tolist()
                    holdings.extend(parse_rows(rows, skipped_out=skipped_out))
        except Exception as e_html:
            logger.debug(f"pd.read_html failed: {e_html}")

    # 3. Try reading as CSV/TSV with python engine
    if not holdings:
        for sep in [None, ",", "\t", ";", "|"]:
            try:
                df = pd.read_csv(io.BytesIO(content), header=None, sep=sep, engine="python", on_bad_lines="skip")
                if not df.empty and df.shape[1] >= 2:
                    rows = df.fillna("").astype(str).values.tolist()
                    holdings.extend(parse_rows(rows, skipped_out=skipped_out))
                    if holdings:
                        break
            except Exception:
                continue

    if not holdings and not (skipped_out and len(skipped_out) > 0):
        raise ValueError(
            "Could not find valid stock holdings in the file. "
            "Please ensure the statement includes equity holdings with Symbol/Scrip Name and Quantity columns."
        )

    return holdings


async def import_file_to_portfolio(db, content: bytes, filename: str, password: Optional[str] = None) -> dict:
    """
    Parse CSV/Excel and upsert into local portfolio DB.
    Returns {created, updated, skipped, errors, preview, total_parsed}
    """
    from app.services import portfolio_service as svc
    from app.schemas.portfolio import HoldingCreate, HoldingUpdate
    from app.models.portfolio import Exchange

    skipped_records = []
    holdings = parse_file(content, filename, password=password, skipped_out=skipped_records)
    created = updated = 0
    skipped = len(skipped_records)
    errors = [f"skipped: {s['symbol']}, {s['reason']}" for s in skipped_records]
    preview = [{"action": "skipped", "symbol": s["symbol"], "reason": s["reason"]} for s in skipped_records]

    for h in holdings:
        exchange = h["exchange"] if h["exchange"] in ("NSE", "BSE") else "NSE"
        try:
            existing = await svc.get_holding_by_symbol(db, h["symbol"], exchange)
            if existing:
                await svc.update_holding(db, existing.id, HoldingUpdate(
                    quantity=h["quantity"],
                    avg_buy_price=h["avg_buy_price"],
                ))
                updated += 1
                preview.append({"action": "updated", "symbol": h["symbol"]})
            else:
                await svc.create_holding(db, HoldingCreate(
                    symbol=h["symbol"],
                    company_name=h["company_name"],
                    exchange=Exchange(exchange),
                    quantity=h["quantity"],
                    avg_buy_price=h["avg_buy_price"],
                ))
                created += 1
                preview.append({"action": "created", "symbol": h["symbol"]})
        except Exception as exc:
            errors.append(f"skipped: {h['symbol']}, {exc}")
            skipped += 1
            preview.append({"action": "error", "symbol": h["symbol"], "reason": str(exc)})

    return {"created": created, "updated": updated, "skipped": skipped,
            "errors": errors, "preview": preview, "total_parsed": len(holdings) + len(skipped_records)}

