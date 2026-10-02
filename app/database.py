from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncAttrs
)
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


# Configure engine arguments depending on DB dialect
engine_kwargs = {"echo": settings.DEBUG, "future": True}
if "sqlite" in settings.DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _ensure_schema(sync_conn):
            from sqlalchemy import inspect, text
            try:
                insp = inspect(sync_conn)
                if "ipos" in insp.get_table_names():
                    cols = {c["name"] for c in insp.get_columns("ipos")}
                    new_cols = [
                        ("sector", "VARCHAR(100)"),
                        ("revenue_growth_yoy", "FLOAT"),
                        ("pat_growth_yoy", "FLOAT"),
                        ("debt_to_equity", "FLOAT"),
                        ("pat_margin_pct", "FLOAT"),
                        ("promoter_holding_pre", "FLOAT"),
                        ("promoter_holding_post", "FLOAT"),
                    ]
                    for col_name, col_type in new_cols:
                        if col_name not in cols:
                            sync_conn.execute(text(f"ALTER TABLE ipos ADD COLUMN {col_name} {col_type}"))
            except Exception:
                pass

        await conn.run_sync(_ensure_schema)

