import logging
from typing import Dict, Any, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["Predictions & Model Evaluation"])


@router.get("/accuracy")
async def get_predictions_accuracy(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Returns direction prediction accuracy, 95% confidence intervals, Brier score,
    after-cost returns, and baseline comparison per model. Includes mandatory disclaimer.
    """
    try:
        report = await PredictionService.get_model_performance(db)
        return report
    except Exception as exc:
        logger.exception("Error fetching prediction accuracy stats")
        raise HTTPException(status_code=500, detail=f"Failed to fetch model accuracy: {exc}")


@router.post("/generate")
async def trigger_prediction_generation(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Manually triggers pre-market direction prediction generation for the watchlist.
    """
    try:
        t_date = date.fromisoformat(target_date) if target_date else date.today()
        preds = await PredictionService.generate_daily_predictions(db, target_date=t_date)
        return {"status": "success", "target_date": str(t_date), "predictions_created": len(preds)}
    except Exception as exc:
        logger.exception("Error during manual prediction generation")
        raise HTTPException(status_code=500, detail=f"Prediction generation failed: {exc}")


@router.post("/score")
async def trigger_prediction_scoring(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Manually triggers post-market scoring of predictions.
    """
    try:
        t_date = date.fromisoformat(target_date) if target_date else None
        results = await PredictionService.score_daily_predictions(db, target_date=t_date)
        return {"status": "success", "results_scored": len(results)}
    except Exception as exc:
        logger.exception("Error during manual prediction scoring")
        raise HTTPException(status_code=500, detail=f"Prediction scoring failed: {exc}")
