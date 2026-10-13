from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.portfolio import Holding, PortfolioSnapshot
    from app.models.mutual_fund import MFHolding


class User(Base):
    """
    User account model for encrypted authentication and user-scoped portfolio management.
    Passwords are encrypted using salted PBKDF2-HMAC-SHA256 (100,000 iterations).
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    holdings: Mapped[List["Holding"]] = relationship(
        "Holding", back_populates="user", cascade="all, delete-orphan"
    )
    mf_holdings: Mapped[List["MFHolding"]] = relationship(
        "MFHolding", back_populates="user", cascade="all, delete-orphan"
    )
    snapshots: Mapped[List["PortfolioSnapshot"]] = relationship(
        "PortfolioSnapshot", back_populates="user", cascade="all, delete-orphan"
    )
