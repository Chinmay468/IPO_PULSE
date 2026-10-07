import enum
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    String, Float, Integer, Date, DateTime, Boolean, Enum, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DirectionType(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class Prediction(Base):
    """
    Directional stock price prediction record.
    Locked upon creation to ensure integrity and prevent post-hoc modifications.
    """
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("target_date", "symbol", "model_name", name="uq_prediction_target_symbol_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    predicted_direction: Mapped[DirectionType] = mapped_column(
        Enum(DirectionType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    features_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    result: Mapped[Optional["PredictionResult"]] = relationship(
        "PredictionResult",
        back_populates="prediction",
        uselist=False,
        cascade="all, delete-orphan"
    )


class PredictionResult(Base):
    """
    Scored outcome for a prediction evaluated after market close.
    """
    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("predictions.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    actual_close: Mapped[float] = mapped_column(Float, nullable=False)
    actual_return: Mapped[float] = mapped_column(Float, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    prediction: Mapped["Prediction"] = relationship("Prediction", back_populates="result")
