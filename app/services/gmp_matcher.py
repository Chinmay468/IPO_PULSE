import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import date, datetime
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ipo import IPO, IPOAlias

logger = logging.getLogger(__name__)

# Global registry of unmatched scraped GMP items across recent runs
last_unmatched_gmp_records: List[Dict[str, Any]] = []


def normalize_for_gmp_match(name: Optional[str]) -> str:
    """
    Standardizes company names for robust GMP matching:
    - Lowercase
    - Strip trailing parenthetical tags like (C), [C]
    - Strip trailing status words (Upcoming, Open, Closed)
    - Strip concatenated exchange/type/status codes (IPOU, IPOO, IPOC, BSE SMEO, NSE SMECT)
    - Strip corporate and business suffixes
    - Strip punctuation and collapse whitespace
    """
    if not name:
        return ""
    s = name.lower()

    # Remove email protection artifacts or @ handles
    s = re.sub(r"\[email&#160;protected\]|\(email protected\)|\[email\s+protected\]", "", s)
    s = re.sub(r"@\S+", "", s)

    # Strip parenthetical status like (c), [c]
    s = re.sub(r"\s*[\(\[]\s*c\s*[\)\]]\s*$", "", s)

    # Strip trailing status words (IPOWatch / InvestorGain)
    s = re.sub(r"(upcoming|open|closed)$", "", s)

    # Strip concatenated exchange, issue type and status tags
    s = re.sub(r"(bse|nse)?\s*(sme)?\s*(ipo)?\s*[uoc|ct]+$", "", s)
    s = re.sub(r"\s*(bse|nse)?\s*(sme)?\s*ipo$", "", s)
    s = re.sub(r"\s*(bse|nse)\s*(sme)?$", "", s)

    # Strip corporate and institutional suffixes
    s = re.sub(
        r"\b(limited|ltd|private|pvt|co|corp|corporation|inc|holdings|group|india|manufacturing|business|technologies|technology|services)\b",
        "",
        s
    )

    # Remove non-alphanumeric punctuation
    s = re.sub(r"[^a-z0-9\s]", " ", s)

    return re.sub(r"\s+", " ", s).strip()


def parse_date_span(date_str: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Parses day and month from strings like '21-23 Oct', '15-19 Oct', '15-Oct', or '13-OctGMP: 91 - 15-OctGMP: 82'.
    Returns (start_day, end_day, month_num).
    """
    if not date_str:
        return None, None, None

    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }

    s = date_str.lower().strip()

    # 1. Look for range with month e.g. '15-19 oct' or '21-23 oct'
    m_range = re.search(r"(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*([a-z]{3})", s)
    if m_range:
        d1, d2, m_str = int(m_range.group(1)), int(m_range.group(2)), m_range.group(3)
        return d1, d2, months.get(m_str)

    # 2. Look for two individual dates e.g. '13-oct - 15-oct' or '13-octgmp: 91 - 15-octgmp: 82'
    dates = re.findall(r"(\d{1,2})\s*[-/]\s*([a-z]{3})", s)
    if len(dates) >= 2:
        d1, m1 = int(dates[0][0]), months.get(dates[0][1])
        d2, m2 = int(dates[1][0]), months.get(dates[1][1])
        return d1, d2, m2 or m1
    elif len(dates) == 1:
        d1, m1 = int(dates[0][0]), months.get(dates[0][1])
        return d1, d1, m1

    return None, None, None


def validate_match_cross_check(scraped_item: Dict[str, Any], ipo: IPO) -> Tuple[bool, str]:
    """
    Cross-checks candidate match against price band and open/close dates:
    - Scraped price must lie inside [band_low - 1, band_high + 1] (or equal issue_price within Rs 1)
      when price information is available.
    - If price band / issue price is missing, fall back to name + dates, marked lower confidence.
    - Dates are a secondary check only: open/close within 2 days (if dates are present).
    Rejects the match when prices or dates disagree.
    """
    # 1. Price Band Cross-Check
    raw_scraped_price = scraped_item.get("price") or scraped_item.get("price_band_high") or scraped_item.get("price_band")
    s_p: Optional[float] = None
    if raw_scraped_price is not None:
        try:
            val = float(raw_scraped_price)
            if val > 0:
                s_p = val
        except (ValueError, TypeError):
            s_p = None

    band_low = float(ipo.price_band_low) if ipo.price_band_low is not None else None
    band_high = float(ipo.price_band_high) if ipo.price_band_high is not None else None
    issue_p = float(ipo.issue_price) if ipo.issue_price is not None else None

    has_db_band = (band_low is not None and band_high is not None)
    has_db_price = has_db_band or (issue_p is not None)

    if s_p is not None and has_db_price:
        if has_db_band:
            inside_band = (band_low - 1.0) <= s_p <= (band_high + 1.0)
            equals_issue = (issue_p is not None and abs(s_p - issue_p) <= 1.0)
            if not (inside_band or equals_issue):
                return False, f"Price conflict: scraped Rs {s_p} lies outside [{band_low - 1.0:.1f}, {band_high + 1.0:.1f}] and issue price {issue_p}"
        elif issue_p is not None:
            if abs(s_p - issue_p) > 1.0:
                return False, f"Price conflict: scraped Rs {s_p} does not equal issue price Rs {issue_p:.1f} within Rs 1 (diff={abs(s_p - issue_p):.2f})"
    else:
        # Missing band or scraped price: fall back to name + dates, marked lower confidence
        scraped_item["lower_confidence_match"] = True

    # 2. Date Secondary Cross-Check (open/close within 2 days)
    scraped_date_raw = scraped_item.get("date_str") or scraped_item.get("date_range")
    if scraped_date_raw and (ipo.open_date or ipo.close_date):
        s_start_d, s_end_d, s_month = parse_date_span(scraped_date_raw)
        if s_month:
            valid_months = [d.month for d in [ipo.open_date, ipo.close_date] if d is not None]
            if valid_months and s_month not in valid_months:
                return False, f"Date month conflict: scraped month {s_month} vs DB months {valid_months}"

        if s_end_d and ipo.close_date:
            if s_month is None or ipo.close_date.month == s_month:
                if abs(ipo.close_date.day - s_end_d) > 2:
                    return False, f"Closing day conflict: scraped close day {s_end_d} vs DB close day {ipo.close_date.day} exceeds 2 days"

        if s_start_d and ipo.open_date:
            if s_month is None or ipo.open_date.month == s_month:
                if abs(ipo.open_date.day - s_start_d) > 2:
                    return False, f"Opening day conflict: scraped open day {s_start_d} vs DB open day {ipo.open_date.day} exceeds 2 days"

    if scraped_item.get("lower_confidence_match"):
        return True, "Passed cross-check (missing price band: lower confidence match based on name and dates)"

    return True, "Passed cross-check"


async def match_gmp_records_to_ipos(
    session: AsyncSession,
    scraped_rows: List[Dict[str, Any]],
    ipos: List[IPO],
    source_name: str
) -> Tuple[List[Tuple[IPO, Dict[str, Any]]], List[Dict[str, Any]]]:
    """
    Matches scraped GMP rows to active/upcoming IPOs using:
    1. Exact alias lookup from ipo_aliases table
    2. Exact normalized company name match
    3. Fuzzy token_set_ratio match (threshold >= 85)
    4. Price and date cross-check validation
    Logs every match and populates the unmatched report.
    """
    global last_unmatched_gmp_records

    # Load existing aliases from DB
    alias_stmt = select(IPOAlias)
    db_aliases = (await session.execute(alias_stmt)).scalars().all()
    # map normalized alias to ipo_id
    alias_to_ipo_id: Dict[str, int] = {}
    for a in db_aliases:
        alias_to_ipo_id[normalize_for_gmp_match(a.alias)] = a.ipo_id

    ipo_by_id: Dict[int, IPO] = {ipo.id: ipo for ipo in ipos}
    norm_to_ipo: Dict[str, IPO] = {}
    for ipo in ipos:
        n = normalize_for_gmp_match(ipo.company_name)
        if n:
            norm_to_ipo[n] = ipo

    matched_pairs: List[Tuple[IPO, Dict[str, Any]]] = []
    unmatched_rows: List[Dict[str, Any]] = []

    for row in scraped_rows:
        raw_name = row.get("company_name", "")
        norm_scraped = normalize_for_gmp_match(raw_name)

        candidate_ipo: Optional[IPO] = None
        match_method = "none"
        match_score = 0.0

        # Step A: Check DB Aliases
        if norm_scraped in alias_to_ipo_id:
            target_id = alias_to_ipo_id[norm_scraped]
            candidate_ipo = ipo_by_id.get(target_id)
            if candidate_ipo:
                match_method = "alias_table"
                match_score = 100.0

        # Step B: Exact normalized match
        if not candidate_ipo and norm_scraped in norm_to_ipo:
            candidate_ipo = norm_to_ipo[norm_scraped]
            match_method = "exact_normalized"
            match_score = 100.0

        # Step C: Fuzzy token matching with rapidfuzz
        if not candidate_ipo and norm_scraped:
            best_ipo = None
            best_score = 0.0
            for ipo_norm, ipo in norm_to_ipo.items():
                t_set = fuzz.token_set_ratio(norm_scraped, ipo_norm)
                t_sort = fuzz.token_sort_ratio(norm_scraped, ipo_norm)
                combined = max(t_set, t_sort)
                if combined > best_score:
                    best_score = combined
                    best_ipo = ipo

            if best_ipo and best_score >= 90.0:
                candidate_ipo = best_ipo
                match_method = "fuzzy_rapidfuzz"
                match_score = best_score

        # Step D: Cross-check validation
        if candidate_ipo:
            valid, reason = validate_match_cross_check(row, candidate_ipo)
            if valid:
                logger.info(
                    f"[GMP Match] Matched '{raw_name}' -> '{candidate_ipo.company_name}' "
                    f"(source={source_name}, method={match_method}, score={match_score:.1f})"
                )
                matched_pairs.append((candidate_ipo, row))
            else:
                logger.warning(
                    f"[GMP Match Rejected] Candidate match '{raw_name}' -> '{candidate_ipo.company_name}' "
                    f"rejected by cross-check: {reason}"
                )
                row["rejection_reason"] = reason
                unmatched_rows.append(row)
        else:
            unmatched_rows.append(row)

    # Record unmatched items globally for reporting
    last_unmatched_gmp_records = unmatched_rows
    if unmatched_rows:
        logger.info(f"[GMP Scraper] {len(unmatched_rows)} rows unmatched from {source_name}.")

    return matched_pairs, unmatched_rows


async def add_ipo_alias(session: AsyncSession, ipo_id: int, alias: str, source: str = "manual") -> IPOAlias:
    """Helper to register a confirmed company name alias."""
    new_alias = IPOAlias(ipo_id=ipo_id, alias=alias.strip(), source=source)
    session.add(new_alias)
    await session.commit()
    logger.info(f"Registered alias '{alias}' for IPO ID {ipo_id} (source={source})")
    return new_alias
