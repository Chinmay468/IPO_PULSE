"""
In-memory CAS (Consolidated Account Statement) PDF parsing service.
Uses casparser library strictly in memory.
Guarantees:
  - Never writes CAS files or fragments to disk.
  - Never logs passwords, PANs, unmasked folios, or statement text.
  - De-duplicates on (folio_hash, date, units, amount).
"""
import hashlib
import io
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import casparser
from casparser.exceptions import IncorrectPasswordError, CASParseError, ParserException

from app.models.mutual_fund import (
    MFScheme,
    MFHolding,
    MFTransaction,
    MFTransactionType
)
from app.services.mf_nav_service import get_amfi_nav_data

logger = logging.getLogger(__name__)


def mask_folio(raw: Optional[str]) -> str:
    """Masks folio numbers, showing at most the last 4 characters."""
    if not raw:
        return "XXXX"
    s = str(raw).strip()
    if len(s) <= 4:
        return "****"
    return "****" + s[-4:]


def hash_folio(raw: Optional[str]) -> str:
    """Computes SHA-256 hash of raw folio string for non-reversible de-duplication."""
    if not raw:
        return "UNKNOWN_FOLIO"
    return hashlib.sha256(str(raw).strip().encode("utf-8")).hexdigest()


def map_tx_type(raw_type: Optional[str], units: float) -> MFTransactionType:
    """Maps casparser TransactionType or raw string to MFTransactionType enum."""
    t = str(raw_type or "").upper()
    if "SIP" in t:
        return MFTransactionType.SIP
    if any(k in t for k in ("REDEMPTION", "SELL")):
        return MFTransactionType.SELL
    if "SWITCH" in t:
        return MFTransactionType.SWITCH
    if "DIVIDEND" in t:
        return MFTransactionType.DIVIDEND
    if any(k in t for k in ("PURCHASE", "BUY", "REINVEST")):
        return MFTransactionType.BUY

    # Fallback based on sign
    return MFTransactionType.BUY if units >= 0 else MFTransactionType.SELL


def parse_cas_pdf_bytes(pdf_bytes: bytes, password: Optional[str] = None) -> dict:
    """
    Parses CAS PDF in memory.
    Raises ValueError on password or parsing failures with clean, sanitized messages.
    """
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise ValueError("File size exceeds 10 MB limit.")

    file_obj = io.BytesIO(pdf_bytes)
    pwd = (password or "").strip()

    try:
        # Never log pwd or investor details
        data = casparser.read_cas_pdf(file_obj, password=pwd, output="dict")
        if hasattr(data, "model_dump"):
            return data.model_dump()
        elif hasattr(data, "dict") and callable(data.dict):
            return data.dict()
        elif isinstance(data, dict):
            return data
        return dict(data)
    except IncorrectPasswordError:
        raise ValueError("Incorrect password provided for the CAS PDF. Please provide the correct PDF password.")
    except (CASParseError, ParserException) as exc:
        raise ValueError(f"Unable to parse CAS PDF statement: {type(exc).__name__}")
    except Exception as exc:
        logger.warning("[CAS Parser] Unexpected parser failure: %s", type(exc).__name__)
        raise ValueError("The provided file could not be parsed as a valid CAMS/KFintech CAS statement.")


async def import_parsed_cas(db: AsyncSession, cas_data: Any, user_id: Optional[int] = None) -> dict:
    """
    Imports parsed CAS dictionary into the database scoped by user_id.
    - Creates or links schemes by AMFI code / ISIN / name.
    - Creates or links holdings by scheme + folio_hash + user_id.
    - De-duplicates transactions on (folio_hash, date, units, amount).
    """
    if hasattr(cas_data, "model_dump"):
        cas_data = cas_data.model_dump()
    elif hasattr(cas_data, "dict") and callable(cas_data.dict):
        cas_data = cas_data.dict()
    elif not isinstance(cas_data, dict):
        try:
            cas_data = dict(cas_data)
        except Exception:
            pass

    folios = cas_data.get("folios", []) or []
    if not folios and "schemes" in cas_data:
        folios = [{"folio": "DEFAULT", "schemes": cas_data.get("schemes", [])}]

    schemes_created = 0
    holdings_created = 0
    tx_imported = 0
    tx_skipped = 0

    # Pre-load cached AMFI NAV dictionary for instant scheme metadata resolution
    amfi_by_code, amfi_by_isin = await get_amfi_nav_data()

    for f in folios:
        raw_folio = f.get("folio", "")
        f_masked = mask_folio(raw_folio)
        f_hash = hash_folio(raw_folio)
        amc_name = f.get("amc")

        schemes = f.get("schemes", []) or []
        for s in schemes:
            scheme_name = str(s.get("scheme", "")).strip()
            if not scheme_name:
                continue

            isin = s.get("isin")
            amfi_code = str(s.get("amfi", "")).strip() if s.get("amfi") else None
            scheme_type = s.get("type")

            # 1. Resolve or Create MFScheme
            scheme_record = None
            if amfi_code:
                res = await db.execute(select(MFScheme).where(MFScheme.scheme_code == amfi_code))
                scheme_record = res.scalars().first()

            if not scheme_record and isin:
                res = await db.execute(select(MFScheme).where(MFScheme.isin == isin))
                scheme_record = res.scalars().first()

            if not scheme_record:
                res = await db.execute(select(MFScheme).where(MFScheme.name == scheme_name))
                scheme_record = res.scalars().first()

            if not scheme_record:
                # Look up AMFI metadata if available
                nav_meta = None
                if amfi_code and amfi_code in amfi_by_code:
                    nav_meta = amfi_by_code[amfi_code]
                elif isin and isin in amfi_by_isin:
                    nav_meta = amfi_by_isin[isin]

                latest_nav = nav_meta["nav"] if nav_meta else None
                latest_date = nav_meta["date"] if nav_meta else None
                plan_type = nav_meta.get("plan_type") if nav_meta else None
                option_type = nav_meta.get("option_type") if nav_meta else None
                cat = nav_meta.get("category") if nav_meta else scheme_type
                amc = nav_meta.get("amc") if nav_meta else amc_name

                # If CAS provides valuation info and AMFI wasn't found, use CAS valuation as initial NAV
                valuation = s.get("valuation", {}) or {}
                if not latest_nav and valuation.get("nav"):
                    try:
                        latest_nav = float(valuation.get("nav", 0))
                        if valuation.get("date"):
                            val_d = valuation.get("date")
                            if isinstance(val_d, str):
                                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                                    try:
                                        latest_date = datetime.strptime(val_d, fmt).date()
                                        break
                                    except ValueError:
                                        pass
                            elif isinstance(val_d, date):
                                latest_date = val_d
                    except Exception:
                        pass

                scheme_record = MFScheme(
                    scheme_code=amfi_code,
                    isin=isin,
                    name=scheme_name,
                    amc=amc,
                    category=cat,
                    plan_type=plan_type,
                    option_type=option_type,
                    latest_nav=latest_nav,
                    latest_nav_date=latest_date,
                    is_nav_stale=False if latest_nav else True,
                )
                db.add(scheme_record)
                await db.flush()
                schemes_created += 1

            # 2. Resolve or Create MFHolding scoped by user_id
            stmt_h = select(MFHolding).where(
                MFHolding.scheme_id == scheme_record.id,
                MFHolding.folio_hash == f_hash
            )
            if user_id is not None:
                stmt_h = stmt_h.where(MFHolding.user_id == user_id)
            else:
                stmt_h = stmt_h.where(MFHolding.user_id.is_(None))
            res_h = await db.execute(stmt_h)
            holding_record = res_h.scalars().first()

            if not holding_record:
                holding_record = MFHolding(
                    scheme_id=scheme_record.id,
                    folio_masked=f_masked,
                    folio_hash=f_hash,
                    units=0.0,
                    user_id=user_id,
                )
                db.add(holding_record)
                await db.flush()
                holdings_created += 1

            # 3. Import & De-duplicate Transactions on (folio_hash, date, units, amount)
            transactions = s.get("transactions", []) or []
            existing_tx_res = await db.execute(
                select(MFTransaction).where(MFTransaction.holding_id == holding_record.id)
            )
            existing_txs = list(existing_tx_res.scalars().all())

            # Map existing by (date, round(units, 4), round(amount, 2))
            existing_set = {
                (tx.date, round(abs(tx.units), 4), round(abs(tx.amount), 2))
                for tx in existing_txs
            }

            for tx in transactions:
                raw_d = tx.get("date")
                if not raw_d:
                    continue

                tx_date = None
                if isinstance(raw_d, str):
                    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                        try:
                            tx_date = datetime.strptime(raw_d, fmt).date()
                            break
                        except ValueError:
                            pass
                elif isinstance(raw_d, date):
                    tx_date = raw_d

                if not tx_date:
                    continue

                try:
                    units = float(tx.get("units") or 0.0)
                    amount = float(tx.get("amount") or 0.0)
                    nav = float(tx.get("nav") or 0.0)
                except (ValueError, TypeError):
                    continue

                # Skip non-holding tax lines or zero entries
                if units == 0 and amount == 0:
                    continue

                # De-duplication check: (date, units, amount) under this holding
                de_dup_key = (tx_date, round(abs(units), 4), round(abs(amount), 2))
                if de_dup_key in existing_set:
                    tx_skipped += 1
                    continue

                mapped_type = map_tx_type(tx.get("type"), units)
                tx_record = MFTransaction(
                    holding_id=holding_record.id,
                    date=tx_date,
                    type=mapped_type,
                    units=abs(units),
                    nav=nav if nav > 0 else (abs(amount) / abs(units) if units != 0 else 0.0),
                    amount=abs(amount) if amount != 0 else (abs(units) * nav)
                )
                db.add(tx_record)
                existing_set.add(de_dup_key)
                tx_imported += 1

            # 4. Update Holding Units
            # Compute total units from closing balance if given, or sum of active transactions
            close_bal = s.get("close") or s.get("close_calculated")
            if close_bal is not None:
                try:
                    holding_record.units = max(0.0, float(close_bal))
                except (ValueError, TypeError):
                    pass
            else:
                # Calculate from transactions
                calc_units = 0.0
                all_tx_res = await db.execute(
                    select(MFTransaction).where(MFTransaction.holding_id == holding_record.id)
                )
                for t in all_tx_res.scalars().all():
                    if t.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND):
                        calc_units += t.units
                    elif t.type == MFTransactionType.SELL:
                        calc_units -= t.units
                    elif t.type == MFTransactionType.SWITCH:
                        # Switch depends on context, defaults to positive units for incoming
                        calc_units += t.units
                holding_record.units = max(0.0, calc_units)

    await db.commit()

    return {
        "schemes_created": schemes_created,
        "holdings_created": holdings_created,
        "transactions_imported": tx_imported,
        "transactions_skipped": tx_skipped,
    }
