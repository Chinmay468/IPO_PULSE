import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import require_auth
from app.config import settings
from app.services.telegram_service import TelegramService

router = APIRouter(prefix="/telegram", tags=["Telegram Notifications"])


@router.get("/status", summary="Get Telegram Bot connection status and settings", dependencies=[Depends(require_auth)])
async def get_telegram_status():
    """
    Returns current Telegram bot integration status without exposing secret tokens.
    """
    configured = TelegramService.is_configured()
    masked_chat = None
    if settings.TELEGRAM_CHAT_ID:
        raw_chat = str(settings.TELEGRAM_CHAT_ID)
        masked_chat = raw_chat[:2] + "****" + raw_chat[-2:] if len(raw_chat) > 4 else "****"

    webhook_info = await TelegramService.get_webhook_info() if configured else {}

    return {
        "configured": configured,
        "notifications_enabled": settings.TELEGRAM_NOTIFICATIONS_ENABLED,
        "chat_id_configured": bool(settings.TELEGRAM_CHAT_ID),
        "chat_id_masked": masked_chat,
        "bot_token_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "min_score": settings.TELEGRAM_MIN_SCORE,
        "min_gmp_pct": settings.TELEGRAM_MIN_GMP_PCT,
        "mainboard_only": settings.TELEGRAM_MAINBOARD_ONLY,
        "webhook_url": settings.TELEGRAM_WEBHOOK_URL,
        "webhook_active": bool(webhook_info.get("result", {}).get("url")),
        "webhook_info": webhook_info.get("result", {})
    }


@router.post("/test", summary="Send a test notification to the configured Telegram bot", dependencies=[Depends(require_auth)])
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


@router.post("/broadcast-best", summary="Immediately scan and send alerts for best active IPOs", dependencies=[Depends(require_auth)])
async def broadcast_best_ipos(db: AsyncSession = Depends(get_db)):
    """
    Scans active and upcoming IPOs and broadcasts real-time alert cards for top investment picks.
    """
    if not TelegramService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables."
        )

    result = await TelegramService.send_best_ipo_alerts(db, force_all=True)
    return result


@router.post("/digest", summary="Send top picks summary digest to Telegram", dependencies=[Depends(require_auth)])
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


@router.post("/webhook/setup", summary="Register webhook with Telegram Bot API", dependencies=[Depends(require_auth)])
async def setup_telegram_webhook():
    """
    Registers the application's webhook URL with Telegram so incoming chat messages are routed here.
    """
    if not TelegramService.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot is not configured."
        )

    success, error = await TelegramService.set_webhook()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to register Telegram webhook: {error}"
        )
    return {"success": True, "webhook_url": settings.TELEGRAM_WEBHOOK_URL}


@router.get("/webhook/info", summary="Check registered webhook info with Telegram Bot API", dependencies=[Depends(require_auth)])
async def get_telegram_webhook_info():
    """
    Fetches the current webhook registration status from Telegram.
    """
    return await TelegramService.get_webhook_info()


@router.post("/webhook", summary="Receive incoming webhook updates from Telegram")
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Public webhook receiver called by Telegram servers to dispatch 2-way bot interactions.
    Validates X-Telegram-Bot-Api-Secret-Token header using constant-time comparison.
    """
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    if expected_secret:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not secret_header or not hmac.compare_digest(secret_header, expected_secret):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Invalid or missing Telegram secret token"
            )

    try:
        update = await request.json()
    except Exception:
        return {"ok": False, "error": "Invalid JSON"}

    return await TelegramService.handle_incoming_update(update, db)

