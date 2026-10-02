import logging
import html
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.ipo import IPO, IPOScore, IPOGmp, IPOSubscription, IPOStatus, RecommendationType

logger = logging.getLogger(__name__)

# In-memory deduplication tracker: ipo_id -> alert_fingerprint
# Keeps alert states so users don't receive identical messages every 15 minutes.
_ALERT_CACHE: Dict[int, str] = {}


class TelegramService:
    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.TELEGRAM_BOT_TOKEN
            and settings.TELEGRAM_CHAT_ID
            and settings.TELEGRAM_NOTIFICATIONS_ENABLED
        )

    @staticmethod
    async def send_message(text: str, parse_mode: str = "HTML") -> Tuple[bool, Optional[str]]:
        """
        Sends a message to the configured Telegram chat via the Bot API.
        Returns (success: bool, error_message: Optional[str]).
        """
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return False, "Telegram bot token or chat ID is not configured."

        if not settings.TELEGRAM_NOTIFICATIONS_ENABLED:
            return False, "Telegram notifications are disabled in settings."

        # Telegram message length limit is 4096 characters
        if len(text) > 4000:
            text = text[:3990] + "\n..."

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return True, None
                err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err_desc = err_data.get("description", f"HTTP {resp.status_code}")
                logger.error(f"Telegram API error: {err_desc}")
                return False, err_desc
        except Exception as exc:
            logger.error(f"Failed to communicate with Telegram API: {exc}")
            return False, str(exc)

    @staticmethod
    def format_ipo_alert(
        ipo: IPO,
        score: Optional[IPOScore] = None,
        gmp: Optional[IPOGmp] = None,
        sub: Optional[IPOSubscription] = None
    ) -> str:
        """
        Formats a single IPO alert with clear institutional indicators and emojis.
        """
        comp_name = html.escape(ipo.company_name or "Unknown Company")
        ipo_type = ipo.ipo_type.value if hasattr(ipo.ipo_type, "value") else str(ipo.ipo_type)
        status_val = ipo.status.value if hasattr(ipo.status, "value") else str(ipo.status)

        rec_str = "APPLY"
        score_val = 0.0
        pos_factors: List[str] = []

        if score:
            rec_str = score.recommendation.value if hasattr(score.recommendation, "value") else str(score.recommendation)
            score_val = getattr(score, "composite_score", getattr(score, "total_score", 0.0)) or 0.0
            if getattr(score, "positive_factors", None):
                pos_factors = score.positive_factors[:3]
            elif score.rationale and isinstance(score.rationale, dict) and score.rationale.get("positive_factors"):
                pos_factors = score.rationale.get("positive_factors", [])[:3]

        # Recommendation badge emoji
        badge = "⭐ <b>STRONG APPLY</b>" if "STRONG" in rec_str else "🟢 <b>APPLY</b>"

        # GMP Information
        gmp_text = "No GMP data yet"
        if gmp and gmp.gmp_amount is not None:
            pct_str = f" (+{gmp.gmp_percentage:.1f}%)" if gmp.gmp_percentage else ""
            gmp_text = f"<b>+₹{gmp.gmp_amount:,.2f}</b>{pct_str}"

        # Price band
        if ipo.price_band_low and ipo.price_band_high:
            price_text = f"₹{ipo.price_band_low:,.0f} - ₹{ipo.price_band_high:,.0f}"
        elif ipo.issue_price:
            price_text = f"₹{ipo.issue_price:,.0f}"
        else:
            price_text = "TBA"

        # Subscription
        sub_mult = getattr(sub, "total_multiple", getattr(sub, "total_subscription", None)) if sub else None
        sub_text = f"{sub_mult:.2f}x" if sub_mult is not None else "Bidding open"

        # Dates
        open_str = ipo.open_date.strftime("%d %b %Y") if ipo.open_date else "TBA"
        close_str = ipo.close_date.strftime("%d %b %Y") if ipo.close_date else "TBA"
        listing_str = ipo.listing_date.strftime("%d %b %Y") if ipo.listing_date else "TBA"

        msg_lines = [
            f"🚀 <b>IPO PULSE ALERT: {comp_name}</b>",
            f"🏷️ <b>Category:</b> {ipo_type} | <b>Status:</b> {status_val.upper()}",
            "",
            f"📊 <b>AI Verdict:</b> {badge}",
            f"🎯 <b>Institutional Score:</b> <b>{score_val:.1f} / 100</b>",
            f"📈 <b>Grey Market Premium (GMP):</b> {gmp_text}",
            f"💰 <b>Price Band:</b> {price_text}",
            f"👥 <b>Subscription:</b> {sub_text}",
            "",
            "📅 <b>Issue Schedule:</b>",
            f"• <b>Opens:</b> {open_str}",
            f"• <b>Closes:</b> {close_str}",
            f"• <b>Listing:</b> {listing_str}",
        ]

        if pos_factors:
            msg_lines.append("")
            msg_lines.append("💡 <b>Key Highlights:</b>")
            for f in pos_factors:
                clean_f = html.escape(f)
                msg_lines.append(f"• {clean_f}")

        msg_lines.append("")
        msg_lines.append("⚡ <i>Automated real-time notification by IPO Pulse Intelligence</i>")

        return "\n".join(msg_lines)

    @classmethod
    async def send_best_ipo_alerts(
        cls,
        session: AsyncSession,
        force_all: bool = False
    ) -> Dict[str, Any]:
        """
        Scans all active/open/upcoming IPOs and sends Telegram notifications for top picks.
        Implements fingerprint deduplication so identical alerts are not resent repeatedly.
        """
        if not cls.is_configured():
            return {
                "configured": False,
                "sent": 0,
                "skipped": 0,
                "reason": "Telegram bot token or chat ID is not configured."
            }

        # Query all upcoming, open, or recently active IPOs
        stmt = (
            select(IPO)
            .where(IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]))
            .options(
                selectinload(IPO.score),
                selectinload(IPO.gmp_records),
                selectinload(IPO.subscriptions)
            )
        )
        res = await session.execute(stmt)
        ipos = res.scalars().all()

        sent_count = 0
        skipped_count = 0
        errors = []

        min_score = settings.TELEGRAM_MIN_SCORE
        min_gmp_pct = settings.TELEGRAM_MIN_GMP_PCT

        for ipo in ipos:
            latest_score = ipo.score
            latest_gmp = max(ipo.gmp_records, key=lambda g: getattr(g, "recorded_at", getattr(g, "created_at", None))) if ipo.gmp_records else None
            latest_sub = max(ipo.subscriptions, key=lambda sb: getattr(sb, "recorded_at", getattr(sb, "created_at", None))) if ipo.subscriptions else None

            # Evaluation criteria:
            score_num = round(getattr(latest_score, "composite_score", getattr(latest_score, "total_score", 0.0)) or 0.0, 1) if latest_score else 0.0
            is_strong = False
            if latest_score:
                rec_val = latest_score.recommendation
                is_strong = (
                    rec_val in [RecommendationType.STRONG_APPLY, RecommendationType.APPLY]
                    or (score_num >= min_score)
                )

            # High GMP booster
            has_high_gmp = False
            if latest_gmp and latest_gmp.gmp_percentage and latest_gmp.gmp_percentage >= min_gmp_pct:
                has_high_gmp = True

            if not (is_strong or has_high_gmp):
                skipped_count += 1
                continue

            # Fingerprint to prevent spamming
            rec_str = latest_score.recommendation.value if (latest_score and hasattr(latest_score.recommendation, "value")) else str(getattr(latest_score, "recommendation", "NONE"))
            gmp_pct = round(latest_gmp.gmp_percentage or 0.0, 1) if latest_gmp else 0.0
            fingerprint = f"{rec_str}:{score_num}:{gmp_pct}"

            if not force_all and _ALERT_CACHE.get(ipo.id) == fingerprint:
                skipped_count += 1
                continue

            # Format and send message
            message = cls.format_ipo_alert(ipo, latest_score, latest_gmp, latest_sub)
            success, err_msg = await cls.send_message(message)

            if success:
                _ALERT_CACHE[ipo.id] = fingerprint
                sent_count += 1
                logger.info(f"Sent Telegram alert for IPO '{ipo.company_name}' (Score: {score_num})")
            else:
                errors.append(f"{ipo.company_name}: {err_msg}")

        return {
            "configured": True,
            "sent": sent_count,
            "skipped": skipped_count,
            "errors": errors
        }

    @classmethod
    async def send_test_message(cls) -> Dict[str, Any]:
        """
        Sends a test message to verify the bot and chat ID configuration.
        """
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return {
                "success": False,
                "error": "Telegram credentials missing. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
            }

        now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M:%S UTC")
        test_msg = (
            "🤖 <b>IPO Pulse Bot Connected!</b>\n\n"
            "✅ Your Telegram bot is active and configured correctly.\n"
            f"🕒 <b>Connected at:</b> {now_str}\n"
            f"🎯 <b>Min Alert Score:</b> {settings.TELEGRAM_MIN_SCORE}/100\n"
            f"📈 <b>Min GMP %:</b> {settings.TELEGRAM_MIN_GMP_PCT}%\n\n"
            "You will now automatically receive real-time alerts whenever a top-tier "
            "(<b>STRONG_APPLY</b>) IPO is detected in the market!"
        )

        success, err = await cls.send_message(test_msg)
        return {
            "success": success,
            "error": err,
            "message": "Test notification delivered successfully." if success else err
        }

    @classmethod
    async def send_top_picks_digest(cls, session: AsyncSession) -> Dict[str, Any]:
        """
        Sends a single compact digest summarizing all currently active top IPOs.
        """
        if not cls.is_configured():
            return {"success": False, "error": "Telegram not configured."}

        stmt = (
            select(IPO)
            .where(IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]))
            .options(
                selectinload(IPO.score),
                selectinload(IPO.gmp_records)
            )
        )
        res = await session.execute(stmt)
        ipos = res.scalars().all()

        picks = []
        for ipo in ipos:
            score = ipo.score
            gmp = max(ipo.gmp_records, key=lambda g: getattr(g, "recorded_at", getattr(g, "created_at", None))) if ipo.gmp_records else None
            score_num = getattr(score, "composite_score", getattr(score, "total_score", 0.0)) or 0.0

            if score and (score.recommendation in [RecommendationType.STRONG_APPLY, RecommendationType.APPLY] or (score_num >= settings.TELEGRAM_MIN_SCORE)):
                picks.append((ipo, score, gmp))

        if not picks:
            msg = "📋 <b>IPO Pulse Daily Digest</b>\n\nNo high-scoring (STRONG_APPLY) IPOs currently active in the market."
            success, err = await cls.send_message(msg)
            return {"success": success, "error": err, "picks_count": 0}

        # Sort by score descending
        picks.sort(key=lambda item: getattr(item[1], "composite_score", getattr(item[1], "total_score", 0.0)) or 0.0, reverse=True)

        lines = [
            "🏆 <b>IPO PULSE: CURRENT TOP INVESTMENT PICKS</b>",
            f"<i>Found {len(picks)} high-potential IPO(s) currently open or upcoming:</i>",
            ""
        ]

        for idx, (ipo, score, gmp) in enumerate(picks, 1):
            comp = html.escape(ipo.company_name)
            rec = "⭐ STRONG APPLY" if "STRONG" in str(score.recommendation) else "🟢 APPLY"
            score_val = getattr(score, "composite_score", getattr(score, "total_score", 0.0)) or 0.0
            gmp_val = f"+{gmp.gmp_percentage:.1f}%" if (gmp and gmp.gmp_percentage) else "N/A"
            lines.append(f"<b>{idx}. {comp}</b>")
            lines.append(f"   • Rating: {rec} (Score: {score_val:.1f})")
            lines.append(f"   • GMP: {gmp_val} | Closes: {ipo.close_date.strftime('%d %b') if ipo.close_date else 'TBA'}")
            lines.append("")

        lines.append("⚡ <i>Stay ahead with IPO Pulse Smart Intelligence</i>")
        msg = "\n".join(lines)

        success, err = await cls.send_message(msg)
        return {"success": success, "error": err, "picks_count": len(picks)}
