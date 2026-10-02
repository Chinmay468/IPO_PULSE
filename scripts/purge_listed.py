import asyncio
from app.database import AsyncSessionLocal
from app.models.ipo import IPO, IPOStatus, IPOScore, IPOGmp, IPOSubscription
from sqlalchemy import delete, select

async def purge():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(IPO.id).where(IPO.status == IPOStatus.LISTED))
        listed_ids = res.scalars().all()
        if listed_ids:
            await db.execute(delete(IPOScore).where(IPOScore.ipo_id.in_(listed_ids)))
            await db.execute(delete(IPOGmp).where(IPOGmp.ipo_id.in_(listed_ids)))
            await db.execute(delete(IPOSubscription).where(IPOSubscription.ipo_id.in_(listed_ids)))
            await db.execute(delete(IPO).where(IPO.id.in_(listed_ids)))
            await db.commit()
            print(f"Successfully purged {len(listed_ids)} listed IPOs: {listed_ids}")
        else:
            print("No listed IPOs found in database.")

if __name__ == "__main__":
    asyncio.run(purge())
