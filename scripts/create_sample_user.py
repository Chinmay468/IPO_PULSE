"""
Create Sample User Account with Stocks & Mutual Funds Data

Creates or updates a user account:
- Username: user
- Password: user123

Populates:
1. Sample Stock Holdings (RELIANCE, TCS, INFY, HDFCBANK, TATAMOTORS) with BUY transactions
2. Sample Mutual Fund Schemes & Holdings (PPFAS Flexi Cap, Mirae Asset Large & Midcap, Nippon India Small Cap)
3. Historical portfolio snapshots for net worth trend visualization
"""

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.auth import hash_password_secure
from app.models.user import User
from app.models.portfolio import Holding, Transaction, TransactionType, Exchange, PortfolioSnapshot
from app.models.mutual_fund import (
    MFScheme, MFHolding, MFTransaction, MFTransactionType, MFNavHistory
)
from app.services.mf_cas_parser_service import mask_folio, hash_folio


async def create_sample_user(db_url: str):
    print("=" * 70)
    print("CREATING SAMPLE USER WITH STOCKS & MUTUAL FUNDS")
    print("=" * 70)
    
    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # 1. Create or update User
        username = "user"
        password_plain = "user123"
        hashed_pw = hash_password_secure(password_plain)

        stmt = select(User).where(User.username == username)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if user:
            print(f"[1/4] User '{username}' already exists (ID: {user.id}). Updating password & status...")
            user.hashed_password = hashed_pw
            user.is_active = True
            user.full_name = "Sample Investor"
            user.email = "user@example.com"
        else:
            print(f"[1/4] Creating new user '{username}'...")
            user = User(
                username=username,
                hashed_password=hashed_pw,
                full_name="Sample Investor",
                email="user@example.com",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.flush()
            print(f"      Created user '{username}' (ID: {user.id})")

        user_id = user.id

        # 2. Add Sample Stocks
        print(f"[2/4] Setting up Sample Stock Holdings for user_id={user_id}...")
        sample_stocks = [
            {
                "symbol": "RELIANCE",
                "company_name": "Reliance Industries Limited",
                "exchange": Exchange.NSE,
                "quantity": 25.0,
                "avg_buy_price": 2740.50,
                "buy_date": date.today() - timedelta(days=120),
            },
            {
                "symbol": "TCS",
                "company_name": "Tata Consultancy Services Ltd",
                "exchange": Exchange.NSE,
                "quantity": 15.0,
                "avg_buy_price": 3820.00,
                "buy_date": date.today() - timedelta(days=95),
            },
            {
                "symbol": "INFY",
                "company_name": "Infosys Limited",
                "exchange": Exchange.NSE,
                "quantity": 40.0,
                "avg_buy_price": 1495.25,
                "buy_date": date.today() - timedelta(days=70),
            },
            {
                "symbol": "HDFCBANK",
                "company_name": "HDFC Bank Limited",
                "exchange": Exchange.NSE,
                "quantity": 35.0,
                "avg_buy_price": 1625.00,
                "buy_date": date.today() - timedelta(days=50),
            },
            {
                "symbol": "TATAMOTORS",
                "company_name": "Tata Motors Limited",
                "exchange": Exchange.NSE,
                "quantity": 50.0,
                "avg_buy_price": 880.00,
                "buy_date": date.today() - timedelta(days=30),
            },
        ]

        for s in sample_stocks:
            stmt_h = select(Holding).where(Holding.user_id == user_id, Holding.symbol == s["symbol"])
            existing_h = (await session.execute(stmt_h)).scalar_one_or_none()
            if existing_h:
                existing_h.company_name = s["company_name"]
                existing_h.quantity = s["quantity"]
                existing_h.avg_buy_price = s["avg_buy_price"]
                existing_h.exchange = s["exchange"]
                print(f"      Updated stock: {s['symbol']} ({s['quantity']} shares @ Rs {s['avg_buy_price']})")
            else:
                new_h = Holding(
                    symbol=s["symbol"],
                    company_name=s["company_name"],
                    exchange=s["exchange"],
                    quantity=s["quantity"],
                    avg_buy_price=s["avg_buy_price"],
                    user_id=user_id,
                )
                session.add(new_h)
                await session.flush()
                # Create BUY transaction
                txn = Transaction(
                    holding_id=new_h.id,
                    transaction_type=TransactionType.BUY,
                    quantity=s["quantity"],
                    price=s["avg_buy_price"],
                    transaction_date=s["buy_date"],
                    notes="Initial position purchase"
                )
                session.add(txn)
                print(f"      Added stock: {s['symbol']} ({s['quantity']} shares @ Rs {s['avg_buy_price']})")

        # 3. Add Sample Mutual Funds
        print(f"[3/4] Setting up Sample Mutual Funds for user_id={user_id}...")
        sample_funds = [
            {
                "scheme_code": "122639",
                "isin": "INF879O01027",
                "name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "amc": "PPFAS Mutual Fund",
                "category": "Flexi Cap Fund",
                "plan_type": "DIRECT",
                "option_type": "GROWTH",
                "units": 450.25,
                "avg_nav": 64.20,
                "latest_nav": 78.45,
                "folio": "1234567/89",
                "buy_date": date.today() - timedelta(days=150),
            },
            {
                "scheme_code": "118834",
                "isin": "INF769K01EZ2",
                "name": "Mirae Asset Large & Midcap Fund - Direct Plan - Growth",
                "amc": "Mirae Asset Mutual Fund",
                "category": "Large & Mid Cap Fund",
                "plan_type": "DIRECT",
                "option_type": "GROWTH",
                "units": 320.10,
                "avg_nav": 118.50,
                "latest_nav": 142.80,
                "folio": "9876543/21",
                "buy_date": date.today() - timedelta(days=110),
            },
            {
                "scheme_code": "118778",
                "isin": "INF204K01U74",
                "name": "Nippon India Small Cap Fund - Direct Plan - Growth",
                "amc": "Nippon India Mutual Fund",
                "category": "Small Cap Fund",
                "plan_type": "DIRECT",
                "option_type": "GROWTH",
                "units": 550.00,
                "avg_nav": 138.40,
                "latest_nav": 178.60,
                "folio": "5544332/11",
                "buy_date": date.today() - timedelta(days=80),
            },
        ]

        for mf in sample_funds:
            # Check or create MFScheme
            stmt_sc = select(MFScheme).where(
                (MFScheme.scheme_code == mf["scheme_code"]) | (MFScheme.isin == mf["isin"])
            )
            scheme = (await session.execute(stmt_sc)).scalar_one_or_none()
            if not scheme:
                scheme = MFScheme(
                    scheme_code=mf["scheme_code"],
                    isin=mf["isin"],
                    name=mf["name"],
                    amc=mf["amc"],
                    category=mf["category"],
                    plan_type=mf["plan_type"],
                    option_type=mf["option_type"],
                    latest_nav=mf["latest_nav"],
                    latest_nav_date=date.today(),
                    is_nav_stale=False,
                )
                session.add(scheme)
                await session.flush()
            else:
                scheme.latest_nav = mf["latest_nav"]
                scheme.latest_nav_date = date.today()
                scheme.is_nav_stale = False

            # Check or create MFHolding for this user
            stmt_mfh = select(MFHolding).where(
                MFHolding.user_id == user_id,
                MFHolding.scheme_id == scheme.id
            )
            mf_holding = (await session.execute(stmt_mfh)).scalar_one_or_none()
            f_masked = mask_folio(mf["folio"])
            f_hash = hash_folio(mf["folio"])

            if mf_holding:
                mf_holding.units = mf["units"]
                mf_holding.folio_masked = f_masked
                mf_holding.folio_hash = f_hash
                print(f"      Updated MF holding: {mf['name'][:35]}... ({mf['units']} units)")
            else:
                mf_holding = MFHolding(
                    scheme_id=scheme.id,
                    user_id=user_id,
                    folio_masked=f_masked,
                    folio_hash=f_hash,
                    units=mf["units"],
                )
                session.add(mf_holding)
                await session.flush()

                # Add initial BUY transaction
                mf_tx = MFTransaction(
                    holding_id=mf_holding.id,
                    date=mf["buy_date"],
                    type=MFTransactionType.BUY,
                    units=mf["units"],
                    nav=mf["avg_nav"],
                    amount=round(mf["units"] * mf["avg_nav"], 2)
                )
                session.add(mf_tx)
                print(f"      Added MF holding: {mf['name'][:35]}... ({mf['units']} units @ NAV Rs {mf['avg_nav']})")

        # 4. Generate Portfolio Snapshot History (past 7 days)
        print(f"[4/4] Creating portfolio snapshot history for user_id={user_id}...")
        # Calculate rough invested and value
        total_stock_invested = sum(s["quantity"] * s["avg_buy_price"] for s in sample_stocks)
        # Approximate current stock value (+6.5% gain)
        total_stock_value = total_stock_invested * 1.065
        
        total_mf_invested = sum(f["units"] * f["avg_nav"] for f in sample_funds)
        total_mf_value = sum(f["units"] * f["latest_nav"] for f in sample_funds)

        combined_invested = round(total_stock_invested + total_mf_invested, 2)
        combined_value = round(total_stock_value + total_mf_value, 2)
        combined_pnl = round(combined_value - combined_invested, 2)

        for i in range(7, -1, -1):
            snap_date = date.today() - timedelta(days=i)
            # Slight daily variance for chart visual
            ratio = 1.0 + (0.005 * (7 - i))
            day_val = round(combined_invested * ratio, 2)
            day_pnl = round(day_val - combined_invested, 2)

            stmt_snap = select(PortfolioSnapshot).where(
                PortfolioSnapshot.user_id == user_id,
                PortfolioSnapshot.date == snap_date
            )
            existing_snap = (await session.execute(stmt_snap)).scalar_one_or_none()
            if existing_snap:
                existing_snap.invested = combined_invested
                existing_snap.current_value = day_val
                existing_snap.pnl = day_pnl
                existing_snap.priced_count = len(sample_stocks)
            else:
                # Check if another record exists for that date (due to global unique constraint on date in legacy schema)
                stmt_any = select(PortfolioSnapshot).where(PortfolioSnapshot.date == snap_date)
                any_snap = (await session.execute(stmt_any)).scalar_one_or_none()
                if any_snap:
                    any_snap.user_id = user_id
                    any_snap.invested = combined_invested
                    any_snap.current_value = day_val
                    any_snap.pnl = day_pnl
                    any_snap.priced_count = len(sample_stocks)
                else:
                    snap = PortfolioSnapshot(
                        user_id=user_id,
                        date=snap_date,
                        invested=combined_invested,
                        current_value=day_val,
                        pnl=day_pnl,
                        priced_count=len(sample_stocks),
                    )
                    session.add(snap)

        await session.commit()
        print("\nSUCCESS: Sample user and portfolio initialized successfully!")
        print(f"Username : {username}")
        print(f"Password : {password_plain}")
        print(f"Stocks   : {len(sample_stocks)} positions (Reliance, TCS, Infosys, HDFC Bank, Tata Motors)")
        print(f"Mutual F.: {len(sample_funds)} schemes (PPFAS Flexi Cap, Mirae Asset Large & Midcap, Nippon Small Cap)")
        print(f"Total Invested: Rs {combined_invested:,.2f}")
        print(f"Current Value : Rs {combined_value:,.2f} (+Rs {combined_pnl:,.2f})")
        print("=" * 70)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create sample user with stocks and mutual funds")
    parser.add_argument("--db-url", type=str, default=None, help="Target SQLAlchemy DB connection URL")
    args = parser.parse_args()

    target_url = args.db_url or os.getenv("DATABASE_URL")
    if not target_url:
        from app.config import settings
        target_url = settings.DATABASE_URL

    asyncio.run(create_sample_user(target_url))
