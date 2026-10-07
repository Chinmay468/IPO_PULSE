import enum
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import (
    String,
    Float,
    Integer,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    func,
    JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class IPOType(str, enum.Enum):
    MAINBOARD = "MAINBOARD"
    SME = "SME"


class IPOStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    LISTED = "LISTED"


class RecommendationType(str, enum.Enum):
    STRONG_APPLY = "STRONG APPLY"
    APPLY = "APPLY"
    NEUTRAL = "NEUTRAL"
    AVOID = "AVOID"


class IPO(Base):
    __tablename__ = "ipos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    ipo_type: Mapped[IPOType] = mapped_column(
        Enum(IPOType, values_callable=lambda obj: [e.value for e in obj]),
        default=IPOType.MAINBOARD,
        nullable=False
    )
    status: Mapped[IPOStatus] = mapped_column(
        Enum(IPOStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=IPOStatus.UPCOMING,
        index=True,
        nullable=False
    )

    # Issue price & Lot details
    price_band_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_band_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    issue_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    listing_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lot_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Size details in Crores INR
    issue_size_crores: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fresh_issue_crores: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ofs_crores: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Key timeline dates
    open_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    allotment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    refunds_initiation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    demat_credit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    listing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Registrar details
    registrar_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    registrar_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Financial / Valuation parameters
    pe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    industry_pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ronw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Return on Net Worth %
    eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Advanced Financial Health & Trend Metrics
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    revenue_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # Revenue Growth % YoY
    pat_growth_yoy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # PAT Growth % YoY
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # Debt / Equity ratio
    pat_margin_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # Net Profit Margin %
    promoter_holding_pre: Mapped[Optional[float]] = mapped_column(Float, nullable=True) # Pre-issue holding %
    promoter_holding_post: Mapped[Optional[float]] = mapped_column(Float, nullable=True)# Post-issue holding %

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    subscriptions: Mapped[List["IPOSubscription"]] = relationship(
        "IPOSubscription",
        back_populates="ipo",
        cascade="all, delete-orphan",
        order_by="desc(IPOSubscription.recorded_at)"
    )
    gmp_records: Mapped[List["IPOGmp"]] = relationship(
        "IPOGmp",
        back_populates="ipo",
        cascade="all, delete-orphan",
        order_by="desc(IPOGmp.recorded_at)"
    )
    score: Mapped[Optional["IPOScore"]] = relationship(
        "IPOScore",
        back_populates="ipo",
        uselist=False,
        cascade="all, delete-orphan"
    )


class IPOSubscription(Base):
    __tablename__ = "ipo_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ipo_id: Mapped[int] = mapped_column(Integer, ForeignKey("ipos.id", ondelete="CASCADE"), index=True, nullable=False)

    qib_multiple: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    nii_multiple: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    retail_multiple: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    employee_multiple: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    total_multiple: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    qib_shares_offered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qib_shares_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nii_shares_offered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    nii_shares_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retail_shares_offered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retail_shares_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_shares_offered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_shares_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    day_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False
    )

    ipo: Mapped["IPO"] = relationship("IPO", back_populates="subscriptions")


class IPOGmp(Base):
    __tablename__ = "ipo_gmp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ipo_id: Mapped[int] = mapped_column(Integer, ForeignKey("ipos.id", ondelete="CASCADE"), index=True, nullable=False)

    gmp_amount: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. Rs 120
    gmp_percentage: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. 24.5 %
    estimated_listing_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kostak_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    subject_to_sauda: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="market", nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False
    )

    ipo: Mapped["IPO"] = relationship("IPO", back_populates="gmp_records")


class IPOScore(Base):
    __tablename__ = "ipo_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    ipo_id: Mapped[int] = mapped_column(Integer, ForeignKey("ipos.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)

    composite_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0 to 100
    recommendation: Mapped[RecommendationType] = mapped_column(
        Enum(RecommendationType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False
    )

    gmp_score: Mapped[float] = mapped_column(Float, default=0.0)  # Max 35
    subscription_score: Mapped[float] = mapped_column(Float, default=0.0)  # Max 30
    valuation_score: Mapped[float] = mapped_column(Float, default=0.0)  # Max 20
    structure_score: Mapped[float] = mapped_column(Float, default=0.0)  # Max 15

    rationale: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    ipo: Mapped["IPO"] = relationship("IPO", back_populates="score")
