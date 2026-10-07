"""
Mutual Funds calculation, summary, and portfolio management service.
Performs all calculations in code (invested, current value, P&L, P&L %, XIRR).
Excludes unpriced holdings from portfolio valuation while tracking their count.
"""
from datetime import date, datetime
import logging
from typing import Optional, List, Dict, Tuple
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mutual_fund import (
    MFScheme,
    MFHolding,
    MFTransaction,
    MFNavHistory,
    MFTransactionType
)
from app.schemas.mutual_fund import (
    MFHoldingCreate,
    MFHoldingUpdate,
    MFHoldingItemResponse,
    MFTransactionCreate,
    MFTransactionResponse,
    MFSummaryResponse,
    MFSchemeHistoryResponse,
    MFNavHistoryPoint,
    AllocationItem,
    CombinedNetWorthResponse,
    StockBreakdown,
    MFBreakdown
)
from app.services.xirr_service import calculate_xirr
from app.services.mf_nav_service import backfill_scheme_history_from_mfapi, get_amfi_nav_data
from app.services import portfolio_service as stock_svc

logger = logging.getLogger(__name__)


def compute_holding_metrics(
    holding: MFHolding,
    scheme: MFScheme,
    today_date: Optional[date] = None
) -> Tuple[float, float, float, float, Optional[float], bool]:
    """
    Computes holding financial metrics:
    Returns (invested, current_value, pnl, pnl_pct, xirr, is_priced)
    """
    if today_date is None:
        today_date = date.today()

    txs = holding.transactions or []
    units = float(holding.units or 0.0)

    # 1. Compute average purchase cost & invested
    buy_amount = 0.0
    buy_units = 0.0
    for t in txs:
        if t.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND):
            buy_amount += float(t.amount)
            buy_units += float(t.units)

    if buy_units > 0:
        avg_nav = buy_amount / buy_units
        invested = round(units * avg_nav, 2)
    else:
        # Fallback if manual holding without transactions
        avg_nav = float(scheme.latest_nav or 0.0) if scheme.latest_nav else 0.0
        invested = round(units * avg_nav, 2)

    # 2. Valuation
    is_priced = bool(scheme.latest_nav and scheme.latest_nav > 0)
    if is_priced:
        current_value = round(units * float(scheme.latest_nav), 2)
        pnl = round(current_value - invested, 2)
        pnl_pct = round((pnl / invested) * 100.0, 2) if invested > 0 else 0.0

        # 3. Cash flows for XIRR
        cashflows: List[Tuple[date, float]] = []
        for t in txs:
            if t.type in (MFTransactionType.BUY, MFTransactionType.SIP):
                cashflows.append((t.date, -abs(float(t.amount))))
            elif t.type == MFTransactionType.SELL:
                cashflows.append((t.date, +abs(float(t.amount))))
            elif t.type == MFTransactionType.DIVIDEND:
                # Dividend payout is positive return
                cashflows.append((t.date, +abs(float(t.amount))))
            elif t.type == MFTransactionType.SWITCH:
                # Switch in as investment
                cashflows.append((t.date, -abs(float(t.amount))))

        # Terminal valuation date
        term_date = scheme.latest_nav_date or today_date
        if current_value > 0:
            cashflows.append((term_date, +current_value))

        if not txs and invested > 0 and current_value > 0:
            # Synthetic single investment cash flow
            init_date = holding.created_at.date() if holding.created_at else term_date
            cashflows = [(init_date, -invested), (term_date, +current_value)]

        xirr_val = calculate_xirr(cashflows)
    else:
        current_value = 0.0
        pnl = 0.0
        pnl_pct = 0.0
        xirr_val = None

    return (invested, current_value, pnl, pnl_pct, xirr_val, is_priced)


async def get_mf_summary(db: AsyncSession) -> MFSummaryResponse:
    """
    Computes overall Mutual Funds summary:
    - Invested, Current Value, P&L, P&L %, overall XIRR.
    - Category & AMC allocations.
    - Excludes unpriced holdings from value while counting and listing them.
    """
    stmt = (
        select(MFHolding)
        .options(
            selectinload(MFHolding.scheme),
            selectinload(MFHolding.transactions)
        )
        .order_by(MFHolding.id.desc())
    )
    res = await db.execute(stmt)
    holdings = list(res.scalars().all())

    today_date = date.today()
    total_invested = 0.0
    current_value = 0.0
    priced_count = 0
    unpriced_count = 0
    unpriced_names: List[str] = []
    nav_dates: List[date] = []

    all_cashflows: List[Tuple[date, float]] = []
    holding_responses: List[MFHoldingItemResponse] = []

    category_sums: Dict[str, float] = {}
    amc_sums: Dict[str, float] = {}

    for h in holdings:
        scheme = h.scheme
        invested, val, pnl, pnl_pct, xirr_val, is_priced = compute_holding_metrics(h, scheme, today_date)

        # Average NAV for display
        buy_amount = sum(float(t.amount) for t in (h.transactions or []) if t.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND))
        buy_units = sum(float(t.units) for t in (h.transactions or []) if t.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND))
        avg_nav = round(buy_amount / buy_units, 4) if buy_units > 0 else (float(scheme.latest_nav or 0.0) if scheme.latest_nav else 0.0)

        if is_priced:
            priced_count += 1
            total_invested += invested
            current_value += val
            if scheme.latest_nav_date:
                nav_dates.append(scheme.latest_nav_date)

            # Accumulate overall cash flows
            for t in (h.transactions or []):
                if t.type in (MFTransactionType.BUY, MFTransactionType.SIP):
                    all_cashflows.append((t.date, -abs(float(t.amount))))
                elif t.type in (MFTransactionType.SELL, MFTransactionType.DIVIDEND):
                    all_cashflows.append((t.date, +abs(float(t.amount))))
                elif t.type == MFTransactionType.SWITCH:
                    all_cashflows.append((t.date, -abs(float(t.amount))))

            term_date = scheme.latest_nav_date or today_date
            if val > 0:
                all_cashflows.append((term_date, +val))

            if not h.transactions and invested > 0 and val > 0:
                init_date = h.created_at.date() if h.created_at else term_date
                all_cashflows.append((init_date, -invested))
                all_cashflows.append((term_date, +val))

            # Allocation aggregates
            cat = scheme.category or "Other"
            category_sums[cat] = category_sums.get(cat, 0.0) + val

            amc = scheme.amc or "Other"
            amc_sums[amc] = amc_sums.get(amc, 0.0) + val
        else:
            unpriced_count += 1
            unpriced_names.append(scheme.name)

        tx_responses = [
            MFTransactionResponse(
                id=t.id,
                holding_id=t.holding_id,
                date=t.date,
                type=t.type,
                units=t.units,
                nav=t.nav,
                amount=t.amount,
                created_at=t.created_at
            )
            for t in (h.transactions or [])
        ]

        holding_responses.append(MFHoldingItemResponse(
            id=h.id,
            scheme_id=scheme.id,
            scheme_name=scheme.name,
            scheme_code=scheme.scheme_code,
            isin=scheme.isin,
            amc=scheme.amc,
            category=scheme.category,
            folio_masked=h.folio_masked,
            units=round(h.units, 4),
            avg_nav=round(avg_nav, 4),
            latest_nav=scheme.latest_nav,
            latest_nav_date=scheme.latest_nav_date,
            is_nav_stale=scheme.is_nav_stale,
            invested=invested,
            current_value=val,
            pnl=pnl,
            pnl_pct=pnl_pct,
            xirr=xirr_val,
            transactions=tx_responses
        ))

    total_invested = round(total_invested, 2)
    current_value = round(current_value, 2)
    total_pnl = round(current_value - total_invested, 2)
    total_pnl_pct = round((total_pnl / total_invested) * 100.0, 2) if total_invested > 0 else 0.0
    overall_xirr = calculate_xirr(all_cashflows)

    nav_as_of_date = max(nav_dates) if nav_dates else None

    # Compute percentage allocations
    category_allocation = [
        AllocationItem(
            name=cat,
            value=round(val, 2),
            percentage=round((val / current_value) * 100.0, 2) if current_value > 0 else 0.0
        )
        for cat, val in sorted(category_sums.items(), key=lambda x: x[1], reverse=True)
    ]

    amc_allocation = [
        AllocationItem(
            name=amc,
            value=round(val, 2),
            percentage=round((val / current_value) * 100.0, 2) if current_value > 0 else 0.0
        )
        for amc, val in sorted(amc_sums.items(), key=lambda x: x[1], reverse=True)
    ]

    return MFSummaryResponse(
        total_invested=total_invested,
        current_value=current_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        overall_xirr=overall_xirr,
        holdings_count=len(holdings),
        priced_count=priced_count,
        unpriced_count=unpriced_count,
        unpriced_holdings=unpriced_names,
        nav_as_of_date=nav_as_of_date,
        category_allocation=category_allocation,
        amc_allocation=amc_allocation,
        holdings=holding_responses
    )


async def get_scheme_nav_history(db: AsyncSession, scheme_id: int) -> MFSchemeHistoryResponse:
    """
    Returns NAV history for a scheme, backfilling from mfapi.in if needed.
    """
    scheme = await db.get(MFScheme, scheme_id)
    if not scheme:
        raise ValueError("Scheme not found")

    res = await db.execute(
        select(MFNavHistory)
        .where(MFNavHistory.scheme_id == scheme_id)
        .order_by(MFNavHistory.date.asc())
    )
    records = list(res.scalars().all())

    # If empty or fewer than 5 days and has scheme_code, attempt backfill
    if len(records) < 5 and scheme.scheme_code:
        await backfill_scheme_history_from_mfapi(db, scheme_id, max_days=365)
        res = await db.execute(
            select(MFNavHistory)
            .where(MFNavHistory.scheme_id == scheme_id)
            .order_by(MFNavHistory.date.asc())
        )
        records = list(res.scalars().all())

    history_points = [
        MFNavHistoryPoint(date=r.date, nav=r.nav)
        for r in records
    ]

    return MFSchemeHistoryResponse(
        scheme_id=scheme.id,
        scheme_name=scheme.name,
        scheme_code=scheme.scheme_code,
        history=history_points
    )


async def create_manual_holding(db: AsyncSession, payload: MFHoldingCreate) -> MFHoldingItemResponse:
    """
    Manually creates a new mutual fund holding and optional initial transaction.
    """
    # 1. Resolve or create scheme
    scheme = None
    if payload.scheme_code:
        res = await db.execute(select(MFScheme).where(MFScheme.scheme_code == payload.scheme_code))
        scheme = res.scalars().first()
    if not scheme and payload.isin:
        res = await db.execute(select(MFScheme).where(MFScheme.isin == payload.isin))
        scheme = res.scalars().first()
    if not scheme:
        res = await db.execute(select(MFScheme).where(MFScheme.name == payload.scheme_name.strip()))
        scheme = res.scalars().first()

    if not scheme:
        # Check AMFI cache
        amfi_by_code, amfi_by_isin = await get_amfi_nav_data()
        meta = None
        if payload.scheme_code and payload.scheme_code in amfi_by_code:
            meta = amfi_by_code[payload.scheme_code]
        elif payload.isin and payload.isin in amfi_by_isin:
            meta = amfi_by_isin[payload.isin]

        nav = meta["nav"] if meta else payload.avg_nav
        dt = meta["date"] if meta else date.today()
        cat = meta.get("category") if meta else payload.category
        amc = meta.get("amc") if meta else payload.amc

        scheme = MFScheme(
            scheme_code=payload.scheme_code,
            isin=payload.isin,
            name=payload.scheme_name.strip(),
            amc=amc,
            category=cat,
            latest_nav=nav,
            latest_nav_date=dt,
            is_nav_stale=False if nav else True
        )
        db.add(scheme)
        await db.flush()

    # 2. Create holding
    from app.services.mf_cas_parser_service import mask_folio, hash_folio
    f_masked = mask_folio(payload.folio_masked)
    f_hash = hash_folio(payload.folio_masked)

    holding = MFHolding(
        scheme_id=scheme.id,
        folio_masked=f_masked,
        folio_hash=f_hash,
        units=payload.units
    )
    db.add(holding)
    await db.flush()

    # 3. Optional initial BUY transaction
    if payload.units > 0 and payload.avg_nav and payload.avg_nav > 0:
        tx = MFTransaction(
            holding_id=holding.id,
            date=date.today(),
            type=MFTransactionType.BUY,
            units=payload.units,
            nav=payload.avg_nav,
            amount=round(payload.units * payload.avg_nav, 2)
        )
        db.add(tx)

    await db.commit()

    # Return refreshed summary item
    stmt = (
        select(MFHolding)
        .options(selectinload(MFHolding.scheme), selectinload(MFHolding.transactions))
        .where(MFHolding.id == holding.id)
    )
    res = await db.execute(stmt)
    refreshed = res.scalar_one()

    invested, val, pnl, pnl_pct, xirr_val, _ = compute_holding_metrics(refreshed, refreshed.scheme)
    return MFHoldingItemResponse(
        id=refreshed.id,
        scheme_id=refreshed.scheme.id,
        scheme_name=refreshed.scheme.name,
        scheme_code=refreshed.scheme.scheme_code,
        isin=refreshed.scheme.isin,
        amc=refreshed.scheme.amc,
        category=refreshed.scheme.category,
        folio_masked=refreshed.folio_masked,
        units=round(refreshed.units, 4),
        avg_nav=payload.avg_nav or 0.0,
        latest_nav=refreshed.scheme.latest_nav,
        latest_nav_date=refreshed.scheme.latest_nav_date,
        is_nav_stale=refreshed.scheme.is_nav_stale,
        invested=invested,
        current_value=val,
        pnl=pnl,
        pnl_pct=pnl_pct,
        xirr=xirr_val,
        transactions=[]
    )


async def update_manual_holding(db: AsyncSession, holding_id: int, payload: MFHoldingUpdate) -> bool:
    """Updates holding units or masked folio."""
    holding = await db.get(MFHolding, holding_id)
    if not holding:
        return False

    if payload.units is not None:
        holding.units = payload.units
    if payload.folio_masked is not None:
        from app.services.mf_cas_parser_service import mask_folio, hash_folio
        holding.folio_masked = mask_folio(payload.folio_masked)
        holding.folio_hash = hash_folio(payload.folio_masked)

    await db.commit()
    return True


async def delete_holding(db: AsyncSession, holding_id: int) -> bool:
    """Deletes a holding and its cascade transactions."""
    holding = await db.get(MFHolding, holding_id)
    if not holding:
        return False
    await db.delete(holding)
    await db.commit()
    return True


async def add_holding_transaction(
    db: AsyncSession, holding_id: int, payload: MFTransactionCreate
) -> MFTransactionResponse:
    """Adds a transaction to a holding and adjusts holding units."""
    holding = await db.get(MFHolding, holding_id)
    if not holding:
        raise ValueError("Holding not found")

    tx = MFTransaction(
        holding_id=holding_id,
        date=payload.date,
        type=payload.type,
        units=payload.units,
        nav=payload.nav,
        amount=payload.amount
    )
    db.add(tx)

    # Adjust holding units
    if payload.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND):
        holding.units += payload.units
    elif payload.type == MFTransactionType.SELL:
        holding.units = max(0.0, holding.units - payload.units)
    elif payload.type == MFTransactionType.SWITCH:
        holding.units += payload.units

    await db.commit()
    await db.refresh(tx)
    return MFTransactionResponse(
        id=tx.id,
        holding_id=tx.holding_id,
        date=tx.date,
        type=tx.type,
        units=tx.units,
        nav=tx.nav,
        amount=tx.amount,
        created_at=tx.created_at
    )


async def delete_holding_transaction(db: AsyncSession, transaction_id: int) -> bool:
    """Deletes a transaction and recalculates holding units."""
    tx = await db.get(MFTransaction, transaction_id)
    if not tx:
        return False

    holding_id = tx.holding_id
    holding = await db.get(MFHolding, holding_id)
    await db.delete(tx)
    await db.flush()

    if holding:
        # Recompute holding units from remaining transactions
        all_tx_res = await db.execute(
            select(MFTransaction).where(MFTransaction.holding_id == holding_id)
        )
        total_u = 0.0
        for t in all_tx_res.scalars().all():
            if t.type in (MFTransactionType.BUY, MFTransactionType.SIP, MFTransactionType.DIVIDEND):
                total_u += t.units
            elif t.type == MFTransactionType.SELL:
                total_u -= t.units
            elif t.type == MFTransactionType.SWITCH:
                total_u += t.units
        holding.units = max(0.0, total_u)

    await db.commit()
    return True


async def get_combined_net_worth(db: AsyncSession) -> CombinedNetWorthResponse:
    """
    Computes combined net worth (stocks + MFs) keeping the two separate in the breakdown.
    """
    stocks_summary = await stock_svc.get_portfolio_summary(db)
    mf_summary = await get_mf_summary(db)

    stocks_pnl = stocks_summary.total_unrealized_pnl
    total_net_worth = round(stocks_summary.current_value + mf_summary.current_value, 2)
    total_invested = round(stocks_summary.total_invested + mf_summary.total_invested, 2)
    total_pnl = round(stocks_pnl + mf_summary.total_pnl, 2)
    total_pnl_pct = round((total_pnl / total_invested) * 100.0, 2) if total_invested > 0 else 0.0

    return CombinedNetWorthResponse(
        total_net_worth=total_net_worth,
        total_invested=total_invested,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        stocks=StockBreakdown(
            invested=stocks_summary.total_invested,
            current_value=stocks_summary.current_value,
            pnl=stocks_summary.total_unrealized_pnl,
            pnl_pct=stocks_summary.total_pnl_pct,
            holdings_count=stocks_summary.holdings_count,
            unpriced_count=stocks_summary.unpriced_count
        ),
        mutual_funds=MFBreakdown(
            invested=mf_summary.total_invested,
            current_value=mf_summary.current_value,
            pnl=mf_summary.total_pnl,
            pnl_pct=mf_summary.total_pnl_pct,
            overall_xirr=mf_summary.overall_xirr,
            holdings_count=mf_summary.holdings_count,
            unpriced_count=mf_summary.unpriced_count,
            nav_as_of_date=mf_summary.nav_as_of_date
        )
    )
