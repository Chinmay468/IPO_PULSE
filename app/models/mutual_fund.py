import enum
from datetime import datetime, date
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    String, Float, Integer, Date, DateTime, Enum, ForeignKey, Boolean, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class MFTransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    SIP = "SIP"
    SWITCH = "SWITCH"
    DIVIDEND = "DIVIDEND"


class MFScheme(Base):
    """Mutual Fund Scheme details, identified by AMFI scheme code and ISIN."""
    __tablename__ = "mf_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    scheme_code: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    isin: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    amc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    plan_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # DIRECT, REGULAR
    option_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # GROWTH, IDCW

    # Latest NAV cached on the scheme
    latest_nav: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latest_nav_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_nav_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    holdings: Mapped[list["MFHolding"]] = relationship(
        "MFHolding", back_populates="scheme", cascade="all, delete-orphan"
    )
    nav_history: Mapped[list["MFNavHistory"]] = relationship(
        "MFNavHistory", back_populates="scheme", cascade="all, delete-orphan",
        order_by="desc(MFNavHistory.date)"
    )


class MFHolding(Base):
    """User holding in a mutual fund scheme under a specific folio."""
    __tablename__ = "mf_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    scheme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mf_schemes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folio_masked: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    folio_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    units: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Scoped user linkage (nullable for backwards-compatibility / admin portfolio)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="mf_holdings")
    scheme: Mapped["MFScheme"] = relationship("MFScheme", back_populates="holdings")
    transactions: Mapped[list["MFTransaction"]] = relationship(
        "MFTransaction", back_populates="holding", cascade="all, delete-orphan",
        order_by="desc(MFTransaction.date)"
    )


class MFTransaction(Base):
    """Individual transaction in a mutual fund holding."""
    __tablename__ = "mf_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mf_holdings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    type: Mapped[MFTransactionType] = mapped_column(
        Enum(MFTransactionType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False
    )
    units: Mapped[float] = mapped_column(Float, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    holding: Mapped["MFHolding"] = relationship("MFHolding", back_populates="transactions")


class MFNavHistory(Base):
    """Historical NAV entries for mutual fund schemes."""
    __tablename__ = "mf_nav_history"
    __table_args__ = (
        UniqueConstraint("scheme_id", "date", name="uq_mf_nav_scheme_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    scheme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mf_schemes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scheme: Mapped["MFScheme"] = relationship("MFScheme", back_populates="nav_history")
