from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    String, Float, Integer, BigInteger, Date, DateTime, Boolean, Text, Index, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PriceHistory(Base):
    """
    Daily OHLCV price history record for tracked symbols.
    """
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "date", name="uq_price_history_symbol_exchange_date"),
        Index("ix_price_history_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataIssue(Base):
    """
    Records data quality issues and flags for price history (e.g. high < low,
    close out of bounds, zero price, large price jumps > 40%, missing trading day gaps).
    """
    __tablename__ = "data_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="WARNING")  # ERROR, WARNING, REVIEW
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
