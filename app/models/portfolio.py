import enum
from datetime import datetime, date
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import (
    String, Float, Integer, Date, DateTime, Enum, ForeignKey, Text, JSON, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    BONUS = "BONUS"
    SPLIT = "SPLIT"


class Exchange(str, enum.Enum):
    NSE = "NSE"
    BSE = "BSE"


class Holding(Base):
    """Current portfolio position for a single stock symbol."""
    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[Exchange] = mapped_column(
        Enum(Exchange, values_callable=lambda obj: [e.value for e in obj]),
        default=Exchange.NSE,
        nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_buy_price: Mapped[float] = mapped_column(Float, nullable=False)

    # Optional linkage to an IPO that was allotted
    ipo_symbol: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Scoped user linkage (nullable for backwards-compatibility / admin portfolio)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="holdings")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="holding",
        cascade="all, delete-orphan",
        order_by="desc(Transaction.transaction_date)"
    )


class Transaction(Base):
    """Individual buy/sell/dividend event for a holding."""
    __tablename__ = "portfolio_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolio_holdings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    holding: Mapped["Holding"] = relationship("Holding", back_populates="transactions")


class SuggestionLog(Base):
    """
    Log of swing stock suggestions made by the bot or application.
    Tracks entry, ATR-based target & stop levels, chronological performance,
    and resolution status (open, target, stop, expired).
    """
    __tablename__ = "suggestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    stop: Mapped[float] = mapped_column(Float, nullable=False)
    atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasons: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="open", nullable=False, index=True
    )  # open, target, stop, expired
    exit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PortfolioSnapshot(Base):
    """Historical valuation snapshots of the portfolio."""
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("date", name="uq_portfolio_snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    invested: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False)
    priced_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Scoped user linkage (nullable for backwards-compatibility / admin snapshot)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="snapshots")


class TechnicalDiagnosis(Base):
    """
    Log of daily mechanical technical diagnoses for portfolio stocks.
    Tracks price, ATR stop, trailing stop, targets, and whether target or stop was hit first.
    """
    __tablename__ = "technical_diagnoses"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_technical_diagnosis_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_stop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_1: Mapped[float] = mapped_column(Float, nullable=False)
    target_2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="OPEN", nullable=False, index=True
    )  # OPEN, TARGET_HIT, STOP_HIT, EXPIRED
    closed_at_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hit_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # TARGET_1, TARGET_2, STOP_LOSS, TRAILING_STOP
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


