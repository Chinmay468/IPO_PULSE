import logging
import html
import re
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


def markdown_to_telegram_html(md_text: str) -> str:
    """
    Safely converts Markdown text into Telegram-compliant HTML.
    Converts bold, italic, code blocks, lists, and headers.
    """
    if not md_text:
        return ""
    
    # 1. Escape basic HTML entities first
    text = html.escape(md_text)
    
    # 2. Code blocks ```code``` -> <pre>code</pre>
    text = re.sub(r'```(?:[a-zA-Z0-9_+-]+)?\n?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    
    # 3. Inline code `code` -> <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # 4. Bold **text** or __text__ -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    
    # 5. Italic *text* or _text_ -> <i>text</i>
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<i>\1</i>', text)
    
    # 6. Markdown headers (# Heading -> <b>Heading</b>)
    text = re.sub(r'^(?:#{1,6})\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # 7. Unordered list bullets (- item or * item -> • item)
    text = re.sub(r'^\s*[-*]\s+', r'• ', text, flags=re.MULTILINE)
    
    return text


class TelegramService:
    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.TELEGRAM_BOT_TOKEN
            and settings.TELEGRAM_CHAT_ID
            and settings.TELEGRAM_NOTIFICATIONS_ENABLED
        )

    @staticmethod
    async def send_message(
        text: str,
        parse_mode: Optional[str] = "HTML",
        chat_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Sends a message to the configured or specified Telegram chat via the Bot API.
        Automatically falls back to plain text if HTML entity parsing fails.
        Returns (success: bool, error_message: Optional[str]).
        """
        target_chat = chat_id or settings.TELEGRAM_CHAT_ID
        if not settings.TELEGRAM_BOT_TOKEN or not target_chat:
            return False, "Telegram bot token or chat ID is not configured."

        if not settings.TELEGRAM_NOTIFICATIONS_ENABLED:
            return False, "Telegram notifications are disabled in settings."

        # Telegram message length limit is 4096 characters
        if len(text) > 4000:
            text = text[:3990] + "\n..."

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return True, None
                err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err_desc = err_data.get("description", f"HTTP {resp.status_code}")
                # If Telegram HTML parsing failed, retry cleanly with plain text
                if parse_mode == "HTML" and ("can't parse entities" in err_desc.lower() or "tag" in err_desc.lower()):
                    payload.pop("parse_mode", None)
                    resp_retry = await client.post(url, json=payload)
                    if resp_retry.status_code == 200:
                        return True, None
                logger.error(f"Telegram API error: {err_desc}")
                return False, err_desc
        except Exception as exc:
            logger.error(f"Failed to communicate with Telegram API: {exc}")
            return False, str(exc)

    @staticmethod
    async def send_chat_action(action: str = "typing", chat_id: Optional[str] = None) -> bool:
        """
        Sends a chat action (e.g. 'typing') to indicate the bot is working.
        """
        target_chat = chat_id or settings.TELEGRAM_CHAT_ID
        if not settings.TELEGRAM_BOT_TOKEN or not target_chat:
            return False
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendChatAction"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json={"chat_id": target_chat, "action": action})
                return True
        except Exception:
            return False

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

    @staticmethod
    def format_portfolio_summary_card(summary: Any) -> str:
        """
        Formats a clean, attractive portfolio summary card for Telegram.
        """
        inv = summary.total_invested or 0.0
        cur = summary.current_value or 0.0
        pnl = summary.total_unrealized_pnl or 0.0
        pnl_pct = summary.total_pnl_pct or 0.0
        day_chg = summary.day_change or 0.0
        day_chg_pct = summary.day_change_pct or 0.0
        count = summary.holdings_count or 0

        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_sign = "+" if pnl > 0 else ""
        day_emoji = "▲" if day_chg >= 0 else "▼"
        day_sign = "+" if day_chg > 0 else ""

        lines = [
            "💼 <b>IPO PULSE · PORTFOLIO SUMMARY</b>",
            "",
            f"💰 <b>Total Invested:</b> ₹{inv:,.2f}",
            f"📈 <b>Current Value:</b> ₹{cur:,.2f}",
            f"{pnl_emoji} <b>Overall P&L:</b> {pnl_sign}₹{pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%)",
            f"📅 <b>Today's Move:</b> {day_sign}₹{day_chg:,.2f} ({day_sign}{day_chg_pct:.2f}%) {day_emoji}",
            f"🎯 <b>Active Positions:</b> {count} stock(s)",
        ]

        if summary.holdings:
            lines.append("")
            lines.append("📋 <b>Top Holdings:</b>")
            sorted_holdings = sorted(summary.holdings, key=lambda h: (h.current_value or 0.0), reverse=True)[:5]
            for h in sorted_holdings:
                h_pnl = h.unrealized_pnl or 0.0
                h_pnl_pct = h.pnl_pct or 0.0
                h_sign = "+" if h_pnl > 0 else ""
                lines.append(f"• <b>{h.symbol}</b> ({h.quantity} sh): ₹{(h.current_value or 0.0):,.0f} | <i>{h_sign}{h_pnl_pct:.1f}%</i>")

        lines.append("")
        lines.append("💬 <i>Reply with any stock symbol (e.g. \"ARMEE\" or \"ITC\") for AI analysis.</i>")
        return "\n".join(lines)

    @staticmethod
    def format_ipo_lookup_card(ipo: IPO) -> str:
        """
        Formats an in-depth scorecard for a specific IPO.
        """
        score = ipo.score
        gmp = max(ipo.gmp_records, key=lambda g: getattr(g, "recorded_at", getattr(g, "created_at", None))) if ipo.gmp_records else None
        sub = max(ipo.subscriptions, key=lambda s: getattr(s, "recorded_at", getattr(s, "created_at", None))) if ipo.subscriptions else None
        return TelegramService.format_ipo_alert(ipo, score, gmp, sub)

    @classmethod
    async def answer_ai_query(cls, query: str, session: AsyncSession) -> str:
        """
        Uses PortfolioAdvisorService to answer investor questions with live holdings & IPO context.
        """
        from app.services.portfolio_service import portfolio_service as pf_svc
        from app.services.portfolio_advisor_service import generate_portfolio_advisory, groq_answer_query

        # 1. Fetch summary & advisory data
        summary = await pf_svc.get_portfolio_summary(session)
        holdings_dict = [h.model_dump() for h in summary.holdings]
        advisory_data = await generate_portfolio_advisory(holdings_dict)
        advisory_data["portfolio_summary"] = summary.model_dump()

        # 2. Fetch active IPOs
        stmt = (
            select(IPO)
            .where(IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]))
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score)
            )
            .order_by(IPO.open_date.asc().nulls_last())
        )
        active_ipos_objs = (await session.execute(stmt)).scalars().all()
        ipos_data = []
        for ipo in active_ipos_objs:
            latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
            latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None

            pband = f"₹{ipo.price_band_low:,.0f} - ₹{ipo.price_band_high:,.0f}" if (ipo.price_band_low and ipo.price_band_high) else (f"₹{ipo.issue_price:,.0f}" if ipo.issue_price else "TBA")
            gmp_str = f"₹{latest_gmp.gmp_amount:,.0f} ({latest_gmp.gmp_percentage:.1f}%)" if latest_gmp else "N/A"
            sub_str = f"{latest_sub.total_multiple:.1f}x" if latest_sub else "N/A"
            score_str = f"{ipo.score.composite_score:.1f}/100" if ipo.score else "N/A"
            rec_str = ipo.score.recommendation.value if ipo.score else "N/A"

            ipos_data.append({
                "symbol": ipo.symbol,
                "company_name": ipo.company_name,
                "status": ipo.status.value,
                "price_band": pband,
                "gmp": gmp_str,
                "subscription": sub_str,
                "score": score_str,
                "recommendation": rec_str
            })

        answer, _source = await groq_answer_query(
            query=query,
            advisory_data=advisory_data,
            chat_history=[],
            active_ipos=ipos_data,
            portfolio_summary=summary,
            db=session
        )
        return answer

    @classmethod
    async def handle_incoming_update(cls, update: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        """
        Processes an incoming Telegram webhook update and dispatches two-way responses.
        """
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"ok": True, "action": "ignored_no_message"}

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()

        if not text:
            return {"ok": True, "action": "ignored_empty_text"}

        # Security check: Only process messages from the authorized chat ID
        configured_chat = str(settings.TELEGRAM_CHAT_ID or "")
        if chat_id != configured_chat:
            logger.warning(f"Unauthorized Telegram message received from chat_id={chat_id}")
            await cls.send_message(
                "🔒 <b>Access Denied</b>\n\nThis IPO Pulse AI bot is private to its configured account.",
                chat_id=chat_id
            )
            return {"ok": True, "action": "unauthorized"}

        # Show typing indicator
        await cls.send_chat_action("typing", chat_id=chat_id)

        clean_lower = text.lower()

        # 1. /start, /help, help
        if clean_lower in ["/start", "/help", "help"]:
            help_text = (
                "👋 <b>Welcome to IPO Pulse AI Bot!</b>\n\n"
                "I am your real-time investment copilot and IPO intelligence assistant.\n\n"
                "⚡ <b>Quick Commands:</b>\n"
                "• 🚀 <b>/top</b> or <b>/best</b> - Current best IPOs to apply for\n"
                "• 💼 <b>/portfolio</b> - Live portfolio summary & today's P&L\n"
                "• 🔍 <b>/ipo &lt;name&gt;</b> - Instant scorecard & GMP for an IPO\n"
                "• ❓ <b>/help</b> - View this command guide\n\n"
                "💬 <b>Ask Me Any Question Directly:</b>\n"
                "• <i>\"Should I apply for Solarium Green?\"</i>\n"
                "• <i>\"How to make my portfolio green?\"</i>\n"
                "• <i>\"What are the stop-loss levels for my stocks?\"</i>\n"
                "• <i>\"Tell me dividends and trailing PE of ITC\"</i>\n\n"
                "Just reply with your question and I'll analyze live market data!"
            )
            await cls.send_message(help_text, chat_id=chat_id)
            return {"ok": True, "action": "help"}

        # 2. /top, /best
        if clean_lower in ["/top", "/best", "top", "best ipo", "best ipos"]:
            digest_res = await cls.send_top_picks_digest(session)
            return {"ok": True, "action": "top_picks", "result": digest_res}

        # 3. /portfolio, /pnl
        if clean_lower in ["/portfolio", "/pnl", "portfolio", "pnl", "my portfolio"]:
            from app.services.portfolio_service import portfolio_service as pf_svc
            summary = await pf_svc.get_portfolio_summary(session)
            card = cls.format_portfolio_summary_card(summary)
            await cls.send_message(card, chat_id=chat_id)
            return {"ok": True, "action": "portfolio"}

        # 4. /ipo <name or symbol>
        if clean_lower.startswith("/ipo "):
            search_term = text[5:].strip()
            if search_term:
                stmt = (
                    select(IPO)
                    .where(
                        (IPO.symbol.ilike(f"%{search_term}%"))
                        | (IPO.company_name.ilike(f"%{search_term}%"))
                    )
                    .options(
                        selectinload(IPO.score),
                        selectinload(IPO.gmp_records),
                        selectinload(IPO.subscriptions)
                    )
                    .limit(1)
                )
                res = await session.execute(stmt)
                found_ipo = res.scalar_one_or_none()
                if found_ipo:
                    card = cls.format_ipo_lookup_card(found_ipo)
                    await cls.send_message(card, chat_id=chat_id)
                    return {"ok": True, "action": "ipo_found"}
                else:
                    await cls.send_message(
                        f"🔍 No IPO found matching <b>{html.escape(search_term)}</b> in active database.",
                        chat_id=chat_id
                    )
                    return {"ok": True, "action": "ipo_not_found"}

        # 5. Natural conversation / AI Copilot query
        try:
            ai_reply = await cls.answer_ai_query(text, session)
            html_reply = markdown_to_telegram_html(ai_reply)
            await cls.send_message(html_reply, chat_id=chat_id)
            return {"ok": True, "action": "ai_answered"}
        except Exception as exc:
            logger.error(f"Error answering AI query on Telegram: {exc}", exc_info=True)
            await cls.send_message(
                f"⚠️ Sorry, I encountered an issue analyzing your query: {html.escape(str(exc))}",
                chat_id=chat_id
            )
            return {"ok": False, "error": str(exc)}

    @classmethod
    async def set_webhook(cls, webhook_url: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Registers the incoming webhook URL with Telegram Bot API.
        """
        url_to_set = webhook_url or settings.TELEGRAM_WEBHOOK_URL
        if not settings.TELEGRAM_BOT_TOKEN:
            return False, "Telegram bot token is not configured."
        if not url_to_set:
            return False, "Webhook URL is not configured."

        api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(api_url, json={"url": url_to_set, "drop_pending_updates": False})
                data = resp.json() if resp.status_code == 200 else {}
                if resp.status_code == 200 and data.get("ok"):
                    logger.info(f"Telegram webhook registered successfully: {url_to_set}")
                    return True, None
                err = data.get("description", f"HTTP {resp.status_code}")
                logger.error(f"Failed to set Telegram webhook: {err}")
                return False, err
        except Exception as exc:
            logger.error(f"Exception setting Telegram webhook: {exc}")
            return False, str(exc)

    @classmethod
    async def get_webhook_info(cls) -> Dict[str, Any]:
        """
        Fetches current webhook status from Telegram.
        """
        if not settings.TELEGRAM_BOT_TOKEN:
            return {"configured": False, "error": "Bot token not configured."}
        api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getWebhookInfo"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(api_url)
                return resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    @classmethod
    async def delete_webhook(cls) -> Tuple[bool, Optional[str]]:
        """
        Deletes the registered webhook from Telegram.
        """
        if not settings.TELEGRAM_BOT_TOKEN:
            return False, "Telegram bot token is not configured."
        api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/deleteWebhook"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(api_url, json={"drop_pending_updates": False})
                data = resp.json() if resp.status_code == 200 else {}
                if resp.status_code == 200 and data.get("ok"):
                    return True, None
                return False, data.get("description", f"HTTP {resp.status_code}")
        except Exception as exc:
            return False, str(exc)

