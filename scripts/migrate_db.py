import asyncio
from sqlalchemy import text, select
from app.database import engine, AsyncSessionLocal
from app.models.ipo import IPO
from app.services.scraper_service import ScraperService

async def run_migration():
    # 1. Add columns to PostgreSQL if not present
    async with engine.begin() as conn:
        cols = [
            ("sector", "VARCHAR(100)"),
            ("revenue_growth_yoy", "FLOAT"),
            ("pat_growth_yoy", "FLOAT"),
            ("debt_to_equity", "FLOAT"),
            ("pat_margin_pct", "FLOAT"),
            ("promoter_holding_pre", "FLOAT"),
            ("promoter_holding_post", "FLOAT")
        ]
        for col, ctype in cols:
            try:
                await conn.execute(text(f"ALTER TABLE ipos ADD COLUMN IF NOT EXISTS {col} {ctype};"))
                print(f"Column {col} verified/added.")
            except Exception as e:
                print(f"Col {col} error: {e}")

    # 2. Re-seed & update existing rows with enriched fundamentals
    async with AsyncSessionLocal() as session:
        seed_count = await ScraperService.seed_market_data(session)
        print(f"Seed processed: {seed_count} records.")
        await session.commit()

        # 3. Recalculate all scores with the new metrics
        sync_res = await ScraperService.sync_market_data(session)
        print("Sync & Score recalculation result:", sync_res)
        await session.commit()

if __name__ == "__main__":
    asyncio.run(run_migration())
