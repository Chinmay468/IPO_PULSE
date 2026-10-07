import pytest
import pytest_asyncio
from datetime import date, timedelta, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.prediction import Prediction, PredictionResult, DirectionType
from app.services.prediction_service import PredictionService, DEFAULT_WATCHLIST
from app.services.telegram_service import TelegramService


@pytest.mark.asyncio
async def test_prediction_creation_and_locked_protection(db_session: AsyncSession):
    """Verifies creation of locked predictions and enforcement of immutability."""
    today = date.today()
    pred = await PredictionService.create_prediction(
        session=db_session,
        target_date=today,
        symbol="RELIANCE",
        model_name="persistence",
        predicted_direction=DirectionType.UP,
        confidence=0.55,
        features_hash="hash123"
    )

    assert pred.id is not None
    assert pred.symbol == "RELIANCE"
    assert pred.model_name == "persistence"
    assert pred.predicted_direction == DirectionType.UP
    assert pred.confidence == 0.55
    assert pred.locked is True

    # Test immutability verification method
    with pytest.raises(PermissionError, match="Locked prediction cannot be modified"):
        PredictionService.verify_locked_protection(pred)

    # Attempting to recreate/update locked prediction returns the existing locked prediction
    dup_pred = await PredictionService.create_prediction(
        session=db_session,
        target_date=today,
        symbol="RELIANCE",
        model_name="persistence",
        predicted_direction=DirectionType.DOWN,
        confidence=0.90,
        features_hash="new_hash"
    )
    assert dup_pred.id == pred.id
    assert dup_pred.predicted_direction == DirectionType.UP  # Retained original


@pytest.mark.asyncio
async def test_prediction_scoring_and_performance_report(db_session: AsyncSession):
    """Verifies scoring of predictions and performance calculation."""
    target_d = date.today() - timedelta(days=1)
    
    p1 = await PredictionService.create_prediction(
        session=db_session,
        target_date=target_d,
        symbol="TCS",
        model_name="persistence",
        predicted_direction=DirectionType.UP,
        confidence=0.60
    )
    p2 = await PredictionService.create_prediction(
        session=db_session,
        target_date=target_d,
        symbol="INFY",
        model_name="always_up",
        predicted_direction=DirectionType.UP,
        confidence=0.50
    )

    # Score manually
    res1 = PredictionResult(
        prediction_id=p1.id,
        actual_close=3500.0,
        actual_return=0.015,
        correct=True,
        scored_at=datetime.now(timezone.utc)
    )
    res2 = PredictionResult(
        prediction_id=p2.id,
        actual_close=1500.0,
        actual_return=-0.02,
        correct=False,
        scored_at=datetime.now(timezone.utc)
    )
    db_session.add_all([res1, res2])
    await db_session.commit()

    report = await PredictionService.get_model_performance(db_session)

    assert "disclaimer" in report
    assert "Research and evaluation only" in report["disclaimer"]
    assert "models" in report
    assert "persistence" in report["models"]
    
    # N < 300 should trigger 'not enough data' notice
    p_info = report["models"]["persistence"]
    assert p_info["status"] == "not enough data"
    assert "Not enough data" in p_info["notice"]
    assert p_info["total_predictions"] == 1


@pytest.mark.asyncio
async def test_accuracy_api_endpoint(client: AsyncClient):
    """Verifies GET /api/v1/predictions/accuracy endpoint response structure and disclaimer."""
    response = await client.get("/api/v1/predictions/accuracy")
    assert response.status_code == 200
    data = response.json()

    assert "disclaimer" in data
    assert "models" in data
    assert "persistence" in data["models"]
    assert "always_up" in data["models"]
    assert "logistic_regression" in data["models"]
    assert "groq_llm" in data["models"]


def test_telegram_accuracy_card():
    """Verifies formatting of Telegram /accuracy command card and disclaimer."""
    mock_report = {
        "disclaimer": "Research and evaluation only, not investment or trading advice.",
        "models": {
            "persistence": {
                "model_name": "persistence",
                "total_predictions": 500,
                "status": "evaluated",
                "accuracy_pct": 52.4,
                "confidence_interval_95": [48.0, 56.8],
                "brier_score": 0.245,
                "simulated_return_pct": 3.2,
                "beats_baselines": False
            },
            "groq_llm": {
                "model_name": "groq_llm",
                "total_predictions": 50,
                "status": "not enough data",
                "notice": "Not enough data (50/300 minimum predictions required)",
                "accuracy_pct": 54.0,
                "confidence_interval_95": [0.0, 0.0],
                "brier_score": 0.0,
                "beats_baselines": False
            }
        }
    }

    card = TelegramService.format_accuracy_card(mock_report)
    assert "MODEL PREDICTION ACCURACY & EVALUATION" in card
    assert "Persistence Baseline" in card
    assert "52.4%" in card
    assert "Not enough data" in card
    assert "Research and evaluation only" in card
