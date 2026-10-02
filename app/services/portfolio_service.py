import logging
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.portfolio import Holding, Transaction, TransactionType
from app.schemas.portfolio import HoldingCreate, HoldingUpdate, TransactionCreate, HoldingResponse, PortfolioSummary
from app.services.market_price_service import get_live_prices_bulk, _yf_symbol
from app.services.portfolio_advisor_service import get_recent_closes_bulk

logger = logging.getLogger(__name__)


# ── Holdings CRUD ────────────────────────────────────────────────────────────

async def list_holdings(db: AsyncSession) -> list[Holding]:
    result = await db.execute(
        select(Holding).options(selectinload(Holding.transactions)).order_by(Holding.symbol)
    )
    return result.scalars().all()


async def get_holding(db: AsyncSession, holding_id: int) -> Optional[Holding]:
    result = await db.execute(
        select(Holding)
        .where(Holding.id == holding_id)
        .options(selectinload(Holding.transactions))
    )
    return result.scalar_one_or_none()


async def get_holding_by_symbol(db: AsyncSession, symbol: str, exchange: str) -> Optional[Holding]:
    result = await db.execute(
        select(Holding)
        .where(Holding.symbol == symbol.upper(), Holding.exchange == exchange)
        .options(selectinload(Holding.transactions))
    )
    return result.scalar_one_or_none()


async def create_holding(db: AsyncSession, data: HoldingCreate) -> Holding:
    holding = Holding(
        symbol=data.symbol.upper(),
        company_name=data.company_name,
        exchange=data.exchange,
        quantity=data.quantity,
        avg_buy_price=data.avg_buy_price,
        ipo_symbol=data.ipo_symbol,
    )
    db.add(holding)
    await db.flush()  # get ID before adding transaction

    # Auto-create the first BUY transaction
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=TransactionType.BUY,
        quantity=data.quantity,
        price=data.avg_buy_price,
        transaction_date=data.initial_transaction_date or date.today(),
        notes="Initial position"
    )
    db.add(txn)
    await db.commit()
    await db.refresh(holding)
    return holding


async def update_holding(db: AsyncSession, holding_id: int, data: HoldingUpdate) -> Optional[Holding]:
    holding = await get_holding(db, holding_id)
    if not holding:
        return None
    if data.company_name is not None:
        holding.company_name = data.company_name
    if data.quantity is not None:
        holding.quantity = data.quantity
    if data.avg_buy_price is not None:
        holding.avg_buy_price = data.avg_buy_price
    await db.commit()
    await db.refresh(holding)
    return holding


async def delete_holding(db: AsyncSession, holding_id: int) -> bool:
    holding = await get_holding(db, holding_id)
    if not holding:
        return False
    await db.delete(holding)
    await db.commit()
    return True


# ── Transactions ─────────────────────────────────────────────────────────────

async def add_transaction(db: AsyncSession, holding_id: int, data: TransactionCreate) -> Optional[Transaction]:
    holding = await get_holding(db, holding_id)
    if not holding:
        return None

    txn = Transaction(
        holding_id=holding_id,
        transaction_type=data.transaction_type,
        quantity=data.quantity,
        price=data.price,
        transaction_date=data.transaction_date,
        notes=data.notes,
    )
    db.add(txn)

    # Recalculate avg_buy_price on BUY
    if data.transaction_type == TransactionType.BUY:
        total_cost = (holding.avg_buy_price * holding.quantity) + (data.price * data.quantity)
        holding.quantity += data.quantity
        holding.avg_buy_price = round(total_cost / holding.quantity, 4) if holding.quantity > 0 else 0

    # Reduce quantity on SELL
    elif data.transaction_type == TransactionType.SELL:
        holding.quantity = max(0, holding.quantity - data.quantity)

    await db.commit()
    await db.refresh(txn)
    return txn


# ── Portfolio Summary (with live prices) ─────────────────────────────────────

async def get_portfolio_summary(db: AsyncSession) -> PortfolioSummary:
    holdings = await list_holdings(db)

    if not holdings:
        return PortfolioSummary(
            total_invested=0, current_value=0, total_unrealized_pnl=0,
            total_pnl_pct=0, day_change=0, day_change_pct=0,
            holdings_count=0, gainers=0, losers=0,
            unpriced_count=0, unpriced_symbols=[],
            holdings=[]
        )

    # Bulk fetch live prices and 7-day trend closes
    sym_exch_pairs = [(h.symbol, h.exchange.value) for h in holdings]
    live_prices = await get_live_prices_bulk(sym_exch_pairs)
    yf_symbols = [_yf_symbol(h.symbol, h.exchange.value) for h in holdings]
    recent_closes = await get_recent_closes_bulk(yf_symbols, count=7)

    enriched: list[HoldingResponse] = []
    priced_invested = 0.0
    current_value = 0.0
    day_change = 0.0
    gainers = losers = 0
    unpriced_count = 0
    unpriced_symbols: list[str] = []

    for h in holdings:
        yf_key = _yf_symbol(h.symbol, h.exchange.value)
        live_price, day_change_pct = live_prices.get(yf_key, (None, None))

        invested = round(h.avg_buy_price * h.quantity, 2)
        curr_val = round(live_price * h.quantity, 2) if live_price is not None else None
        unrealized_pnl = round(curr_val - invested, 2) if curr_val is not None else None
        pnl_pct = round(((curr_val - invested) / invested) * 100, 2) if curr_val is not None and invested > 0 else None

        if live_price is not None:
            priced_invested += invested
            current_value += curr_val
            if day_change_pct:
                prev_val = curr_val / (1 + day_change_pct / 100)
                day_change += (curr_val - prev_val)
            if unrealized_pnl is not None:
                if unrealized_pnl > 0:
                    gainers += 1
                elif unrealized_pnl < 0:
                    losers += 1
        else:
            unpriced_count += 1
            unpriced_symbols.append(h.symbol)

        enriched.append(HoldingResponse(
            id=h.id,
            symbol=h.symbol,
            company_name=h.company_name,
            exchange=h.exchange,
            quantity=h.quantity,
            avg_buy_price=h.avg_buy_price,
            ipo_symbol=h.ipo_symbol,
            created_at=h.created_at,
            updated_at=h.updated_at,
            live_price=live_price,
            current_value=curr_val,
            invested_value=invested,
            unrealized_pnl=unrealized_pnl,
            pnl_pct=pnl_pct,
            day_change_pct=day_change_pct,
            trend_closes=recent_closes.get(yf_key) or None,
            transactions=[],  # omit in summary for performance
        ))

    total_invested = round(priced_invested, 2)
    current_value = round(current_value, 2)
    overall_pnl = round(current_value - total_invested, 2)
    overall_pnl_pct = round((overall_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0
    day_chg_pct = round((day_change / (current_value - day_change)) * 100, 2) if (current_value - day_change) > 0 else 0.0

    return PortfolioSummary(
        total_invested=total_invested,
        current_value=current_value,
        total_unrealized_pnl=overall_pnl,
        total_pnl_pct=overall_pnl_pct,
        day_change=round(day_change, 2),
        day_change_pct=day_chg_pct,
        holdings_count=len(holdings),
        gainers=gainers,
        losers=losers,
        unpriced_count=unpriced_count,
        unpriced_symbols=unpriced_symbols,
        holdings=enriched,
        last_updated=datetime.now(timezone.utc),
    )


# ── Backwards-Compatibility Namespace ───────────────────────────────────────
class _PortfolioServiceProxy:
    get_portfolio_summary = staticmethod(get_portfolio_summary)
    list_holdings = staticmethod(list_holdings)
    get_holding = staticmethod(get_holding)
    get_holding_by_symbol = staticmethod(get_holding_by_symbol)

portfolio_service = _PortfolioServiceProxy()


