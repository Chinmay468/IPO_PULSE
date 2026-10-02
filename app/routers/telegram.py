from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import require_auth
from app.config import settings
from app.services.telegram_service import TelegramService

router = APIRouter(prefix="/telegram", tags=["Telegram Notifications"], dependencies=[Depends(require_auth)])


@router.get("/status", summary="Get Telegram Bot connection status and settings")
async def get_telegram_status():
    """
    Returns current Telegram bot integration status without exposing secret tokens.
    """
    configured = TelegramService.is_configured()
    masked_chat = None
    if settings.TELEGRAM_CHAT_ID:
        raw_chat = str(settings.TELEGRAM_CHAT_ID)
        masked_chat = raw_chat[:2] + "****" + raw_chat[-2:] if len(raw_chat) > 4 else "****"

    return {
        "configured": configured,
        "notifications_enabled": settings.TELEGRAM_NOTIFICATIONS_ENABLED,
        "chat_id_configured": bool(settings.TELEGRAM_CHAT_ID),
        "chat_id_masked": masked_chat,
        "bot_token_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "min_score": settings.TELEGRAM_MIN_SCORE,
        "min_gmp_pct": settings.TELEGRAM_MIN_GMP_PCT
    }


@router.post("/test", summary="Send a test notification to the configured Telegram bot")
async def send_test_notification():
    """
    Sends an immediate verification message to the configured Telegram chat.
    """
    if not TelegramService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables."
        )

    res = await TelegramService.send_test_message()
    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram API delivery failed: {res.get('error')}"
        )

    return res


@router.post("/broadcast-best", summary="Immediately scan and send alerts for best active IPOs")
async def broadcast_best_ipos(db: AsyncSession = Depends(get_db)):
    """
    Scans active and upcoming IPOs and broadcasts real-time alert cards for top investment picks.
    """
    if not TelegramService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables."
        )

    # force_all=True for manual broadcast trigger so user gets immediate alerts
    result = await TelegramService.send_best_ipo_alerts(db, force_all=True)
    return result


@router.post("/digest", summary="Send top picks summary digest to Telegram")
async def send_top_picks_digest(db: AsyncSession = Depends(get_db)):
    """
    Sends a formatted summary of the currently active top IPOs in a single Telegram message.
    """
    if not TelegramService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables."
        )

    result = await TelegramService.send_top_picks_digest(db)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram delivery failed: {result.get('error')}"
        )

    return result
