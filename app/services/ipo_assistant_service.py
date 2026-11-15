import asyncio
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.services import gemini_client_service as gcs
from app.services.groq_client_service import groq_key_pool

logger = logging.getLogger(__name__)

# Out-of-scope triggers (crypto, forex, commodities, prompt extraction, coding, etc.)
OUT_OF_SCOPE_TRIGGERS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "doge", "solana", "forex", "usd/inr",
    "usd to inr", "dollar", "euro", "yen", "gbp", "futures", "repo rate", "inflation",
    "nifty", "sensex", "girega", "chadhega", "openai", "spacex", "stripe", "bytedance", "unlisted",
    "guarantee", "risk-free", "risk free", "100% sure", "sure-shot", "winning stock",
    "promise me", "double next month", "system prompt", "bot token", "api key",
    "hidden prompt", "repeat everything", "system override", "jailbreak", "instructions given to you",
    "confidential instructions", "ignore previous", "disregard", "secret", "reveal your",
    "gold price", "silver price", "forecast gold", "forecast silver",
    "another user", "other user", "user's data", "someone else", "admin password",
    "webhook secret", "secret token", "print your prompt", "show prompt", "ignore rules",
    "bypass", "root shell", "hack", "weather", "write code", "python code", "translate to",
    "free money", "private .env", ".env file", "database password", "exfiltrate",
    "postgres", "superuser", "pg_dump", "sql dump", "database dump",
    "portfolio", "holding", "my shares", "my stocks", "mutual fund", "nav", "xirr"
]

IPO_GLOSSARY = {
    "sebi": (
        "**Securities and Exchange Board of India (SEBI)** is the apex statutory regulatory body "
        "established under the SEBI Act, 1992 to protect the interests of investors in securities and to promote "
        "and regulate the securities market in India. (general knowledge)"
    ),
    "ipo": (
        "An **Initial Public Offering (IPO)** is the process by which a private corporation can go public by sale "
        "of its stocks to the general public. It could be a new, young company or an old company which decides to be "
        "listed on an exchange and hence goes public. (general knowledge)"
    ),
    "gmp": (
        "**Grey Market Premium (GMP)** is an unofficial, unregulated premium at which IPO shares trade in the "
        "grey market before they officially list on the stock exchange (NSE/BSE). A positive GMP indicates buyer demand "
        "above the issue price, while a negative GMP indicates discounting. (general knowledge)"
    ),
    "price band": (
        "A **Price Band** is the value band within which investors can bid for shares in an IPO. The difference between "
        "the floor price (minimum) and cap price (maximum) is regulated by SEBI (maximum 20% spread). (general knowledge)"
    ),
    "allotment": (
        "**IPO Allotment** is the process where the registrar (such as Link Intime, KFintech, Bigshare) allocates "
        "shares to applicants based on demand and SEBI allotment rules (e.g. lottery system for oversubscribed retail categories). (general knowledge)"
    ),
    "stop loss": (
        "A **Stop Loss** is an advance order placed to sell a security when it reaches a specific price point, "
        "designed to limit an investor's potential loss on a position. (general knowledge)"
    ),
    "rhp": (
        "A **Red Herring Prospectus (RHP)** is a preliminary registration document filed by a company with SEBI "
        "before an IPO, containing complete details of operations, financials, and objectives, but omitting the final issue price. (general knowledge)"
    ),
    "drhp": (
        "A **Draft Red Herring Prospectus (DRHP)** is the initial draft prospectus submitted to SEBI for review "
        "and public comments before regulatory clearance. (general knowledge)"
    ),
    "anchor investor": (
        "**Anchor Investors** are Qualified Institutional Buyers (QIBs) who apply for a minimum value of ₹10 crore "
        "in an IPO, allocated up to 60% of the QIB portion on the day before the IPO opens, subject to lock-in periods. (general knowledge)"
    )
}


def answer_ipo_query(
    query: str,
    active_ipos: Optional[List[Dict[str, Any]]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any
) -> str:
    """
    Deterministic rule-engine / fallback response generator for IPO queries.
    Handles out-of-scope refusals, glossary definitions, live/upcoming IPO lookups, and time-sensitive warnings.
    """
    q = query.lower().strip()

    # 1. Out of scope / security guardrail
    if any(trigger in q for trigger in OUT_OF_SCOPE_TRIGGERS):
        return (
            "🛡️ **Out of Scope / Guardrail Notice:**\n\n"
            "I am the IPO Pulse Assistant. I strictly focus on Indian IPOs (Mainboard & SME), Grey Market Premium (GMP), "
            "subscription demand, allotment status, and algorithmic IPO scoring (0-100).\n\n"
            "• **IPO Focus:** I do not track personal stock portfolios, mutual funds, or secondary market swing trades.\n"
            "• **Market Risk:** IPO investments carry market risk; no listing gains or returns can be guaranteed.\n"
            "• **Security:** Developer instructions, system prompts, and credentials cannot be revealed."
        )

    # 2. Time-sensitive queries without live search
    if any(k in q for k in ["who is the current", "who is the chairperson", "who is sebi chief", "current sebi chairperson", "rbi governor"]):
        if "sebi" in q:
            return "I can't confirm this live, check sebi.gov.in."
        if "rbi" in q:
            return "I can't confirm this live, check rbi.org.in."
        return "I can't confirm this live, check official regulatory sources."

    # 3. Glossary definitions
    for term, definition in IPO_GLOSSARY.items():
        if f"what is {term}" in q or f"what is a {term}" in q or f"what is an {term}" in q or f"explain {term}" in q or q == term:
            return definition
        if term == "sebi" and ("define sebi" in q or "who is sebi" in q):
            return definition

    # 4. Live / Upcoming / Recommendations lookup from active_ipos
    if active_ipos:
        # Upcoming
        if any(k in q for k in ["upcoming", "next ipo", "future ipo", "coming ipo"]):
            upcoming_list = [i for i in active_ipos if str(i.get("status", "")).upper() == "UPCOMING"]
            if upcoming_list:
                lines = ["📅 **Upcoming Mainboard IPOs (Scheduled for Future)**\n"]
                for ipo in upcoming_list:
                    i_sym = ipo.get("symbol", "")
                    i_name = ipo.get("company_name", i_sym)
                    band = ipo.get("price_band", "TBA")
                    gmp = ipo.get("gmp", "N/A")
                    score = ipo.get("score", "N/A")
                    open_d = ipo.get("open_date") or "TBA"
                    close_d = ipo.get("close_date") or "TBA"
                    lines.append(f"• **{i_name}** (`{i_sym}`): Dates: {open_d} to {close_d} | Band: {band} | GMP: {gmp} | Score: {score}")
                return "\n".join(lines)
            else:
                live_list = [i for i in active_ipos if str(i.get("status", "")).upper() == "LIVE"]
                live_names = ", ".join(f"**{i.get('company_name', i.get('symbol'))}**" for i in live_list[:2]) if live_list else "None"
                return (
                    "📅 **Upcoming Mainboard IPOs**\n\n"
                    "There are currently no upcoming Mainboard IPOs scheduled in the tracker.\n\n"
                    f"💡 *Currently LIVE IPOs:* {live_names}."
                )

        # Live
        if any(k in q for k in ["live ipo", "open ipo", "currently open", "current ipo"]):
            live_list = [i for i in active_ipos if str(i.get("status", "")).upper() == "LIVE"]
            if live_list:
                lines = ["🚀 **Live Mainboard IPOs (Currently Open for Bidding)**\n"]
                for ipo in live_list:
                    i_sym = ipo.get("symbol", "")
                    i_name = ipo.get("company_name", i_sym)
                    band = ipo.get("price_band", "TBA")
                    gmp = ipo.get("gmp", "N/A")
                    sub = ipo.get("subscription", "N/A")
                    score = ipo.get("score", "N/A")
                    rec = ipo.get("recommendation", "N/A")
                    lines.append(f"• **{i_name}** (`{i_sym}`): Band: {band} | GMP: {gmp} | Sub: {sub} | Score: {score} ({rec})")
                return "\n".join(lines)
            return "There are currently no live IPOs open for bidding today."

        # Top / Recommended
        if any(k in q for k in ["best ipo", "top ipo", "which ipo to apply", "should i apply", "highest score", "recommend"]):
            def _extract_score(item: Dict[str, Any]) -> float:
                s = str(item.get("score", "")).split("/")[0]
                try:
                    return float(s)
                except ValueError:
                    return -1.0

            sorted_ipos = sorted(active_ipos, key=_extract_score, reverse=True)
            if sorted_ipos:
                lines = ["🚀 **Top Active IPO Opportunities (Algorithmic Ranking)**\n"]
                for ipo in sorted_ipos[:3]:
                    i_sym = ipo.get("symbol", "")
                    i_name = ipo.get("company_name", i_sym)
                    gmp = ipo.get("gmp", "N/A")
                    score = ipo.get("score", "N/A")
                    rec = ipo.get("recommendation", "N/A")
                    lines.append(f"• **{i_name}** (`{i_sym}`): Score: **{score}** ({rec}) | GMP: {gmp}")
                return "\n".join(lines)

        # Check for specific IPO name/symbol
        for item in active_ipos:
            sym_clean = item.get("symbol", "").lower()
            name_clean = item.get("company_name", "").lower()
            if (sym_clean and sym_clean in q) or (name_clean and any(part in q for part in name_clean.split() if len(part) > 3)):
                return (
                    f"🏢 **{item.get('company_name', item.get('symbol'))}** (`{item.get('symbol')}`)\n\n"
                    f"• **Status:** {item.get('status', 'N/A')}\n"
                    f"• **Price Band:** {item.get('price_band', 'TBA')}\n"
                    f"• **Grey Market Premium (GMP):** {item.get('gmp', 'N/A')}\n"
                    f"• **Subscription Demand:** {item.get('subscription', 'N/A')}\n"
                    f"• **Algorithmic Score:** {item.get('score', 'N/A')} ({item.get('recommendation', 'N/A')})\n"
                    f"• **Issue Period:** {item.get('open_date', 'TBA')} to {item.get('close_date', 'TBA')}"
                )

    return (
        "💡 I am your IPO Pulse Copilot. You can ask me about:\n"
        "• Active & upcoming Indian IPOs (Mainboard & SME)\n"
        "• Latest Grey Market Premium (GMP) rates and trends\n"
        "• Subscription multiples (QIB, NII, Retail)\n"
        "• Allotment status, registrar details, and dates\n"
        "• 0-100 composite score breakdowns and recommendation analysis."
    )


async def fetch_active_ipos_data(db: Any) -> List[Dict[str, Any]]:
    """Helper to query live & upcoming IPOs with score and latest GMP/subscription."""
    if not db:
        return []
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.ipo import IPO, IPOStatus

        stmt = (
            select(IPO)
            .where(
                IPO.status.in_([IPOStatus.LIVE, IPOStatus.UPCOMING]),
                IPO.is_seed.is_(False)
            )
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score)
            )
            .order_by(IPO.open_date.asc().nulls_last())
        )
        active_ipos_objs = (await db.execute(stmt)).scalars().all()
        ipos_data = []
        for ipo in active_ipos_objs:
            latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
            latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None

            if ipo.price_band_low is not None and ipo.price_band_high is not None:
                pband = f"₹{ipo.price_band_low:,.0f} - ₹{ipo.price_band_high:,.0f}"
            elif ipo.issue_price is not None:
                pband = f"₹{ipo.issue_price:,.0f}"
            else:
                pband = "TBA"

            if latest_gmp and latest_gmp.gmp_amount is not None:
                if latest_gmp.gmp_percentage is not None:
                    gmp_str = f"₹{latest_gmp.gmp_amount:,.0f} ({latest_gmp.gmp_percentage:.1f}%)"
                else:
                    gmp_str = f"₹{latest_gmp.gmp_amount:,.0f}"
            else:
                gmp_str = "N/A"

            if latest_sub and latest_sub.total_multiple is not None:
                sub_str = f"Total {latest_sub.total_multiple:.1f}x (QIB {latest_sub.qib_multiple or 0:.1f}x, Retail {latest_sub.retail_multiple or 0:.1f}x)"
            else:
                sub_str = "N/A"

            score_str = f"{ipo.score.composite_score:.1f}/100" if (ipo.score and ipo.score.composite_score is not None) else "N/A"
            rec_str = getattr(ipo.score.recommendation, "value", str(ipo.score.recommendation)) if (ipo.score and ipo.score.recommendation) else "N/A"

            ipos_data.append({
                "symbol": ipo.symbol,
                "company_name": ipo.company_name,
                "status": getattr(ipo.status, "value", str(ipo.status)),
                "ipo_type": getattr(ipo.ipo_type, "value", str(ipo.ipo_type)) if ipo.ipo_type else "Mainboard",
                "open_date": str(ipo.open_date) if ipo.open_date else None,
                "close_date": str(ipo.close_date) if ipo.close_date else None,
                "price_band": pband,
                "gmp": gmp_str,
                "subscription": sub_str,
                "score": score_str,
                "recommendation": rec_str
            })
        return ipos_data
    except Exception as exc:
        logger.warning("Could not fetch active IPOs for assistant: %s", exc)
        return []


async def groq_answer_ipo_query(
    query: str,
    active_ipos: Optional[List[Dict[str, Any]]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    db: Optional[Any] = None,
    force_llm: bool = False,
    return_model: bool = False,
    **kwargs: Any
) -> Tuple[str, str] | Tuple[str, str, str]:
    """
    Routes an IPO query through Gemini or Groq with live IPO context.
    Executes smart key rotation, provider failover, and falls back to deterministic rule engine if needed.
    """
    start_time = time.perf_counter()

    if active_ipos is None and db is not None:
        active_ipos = await fetch_active_ipos_data(db)

    gemini_key = gcs.get_gemini_api_key()
    available_groq_keys = groq_key_pool.get_all_keys()
    primary_pref = (os.getenv("PRIMARY_LLM_PROVIDER") or getattr(settings, "PRIMARY_LLM_PROVIDER", "gemini")).strip().lower()

    providers_to_try = []
    if primary_pref == "gemini":
        if gemini_key:
            providers_to_try.append("gemini")
        if available_groq_keys:
            providers_to_try.append("groq")
    else:
        if available_groq_keys:
            providers_to_try.append("groq")
        if gemini_key:
            providers_to_try.append("gemini")

    if not providers_to_try:
        if force_llm:
            raise RuntimeError("Neither GROQ_API_KEY nor GEMINI_API_KEY is configured.")
        fallback_ans = answer_ipo_query(query, active_ipos=active_ipos, chat_history=chat_history)
        return (fallback_ans, "fallback", "rule_engine") if return_model else (fallback_ans, "fallback")

    # 1. Build context
    live_items = [i for i in (active_ipos or []) if str(i.get("status", "")).upper() == "LIVE"]
    upcoming_items = [i for i in (active_ipos or []) if str(i.get("status", "")).upper() == "UPCOMING"]

    live_text = "\n".join(
        f"• {i.get('company_name')} ({i.get('symbol')}): Type: {i.get('ipo_type', 'Mainboard')} | "
        f"Band: {i.get('price_band')} | GMP: {i.get('gmp')} | Sub: {i.get('subscription')} | "
        f"Score: {i.get('score')} ({i.get('recommendation')}) | Dates: {i.get('open_date')} to {i.get('close_date')}"
        for i in live_items
    ) or "None currently open."

    upcoming_text = "\n".join(
        f"• {i.get('company_name')} ({i.get('symbol')}): Type: {i.get('ipo_type', 'Mainboard')} | "
        f"Band: {i.get('price_band')} | GMP: {i.get('gmp')} | Score: {i.get('score')} | Dates: {i.get('open_date')} to {i.get('close_date')}"
        for i in upcoming_items
    ) or "None scheduled."

    system_prompt = (
        "You are the IPO Pulse Assistant, an AI expert specializing in Indian Initial Public Offerings (NSE/BSE).\n"
        "Rules:\n"
        "1. Strictly answer questions about Indian IPOs (Mainboard & SME), Grey Market Premium (GMP), subscription multiples, "
        "allotment status, and IPO Pulse algorithmic scores (0-100) using the context below.\n"
        "2. Do not answer questions about personal stock portfolios, mutual funds, swing trading, crypto, or general coding.\n"
        "3. Provide balanced risk analysis: highlight subscription interest, financial health, valuation, and GMP.\n"
        "4. Never guarantee listing gains or risk-free profits. All equity investments carry risk.\n\n"
        "## Current Live IPOs (Open for Bidding)\n"
        f"{live_text}\n\n"
        "## Upcoming IPOs (Scheduled)\n"
        f"{upcoming_text}\n"
    )

    q_lower = query.lower()
    is_time_sensitive = any(w in q_lower for w in ["who is", "current", "latest rule", "chairperson", "governor", "president", "head of sebi"])

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if chat_history and isinstance(chat_history, list):
        for msg in chat_history[-6:]:
            if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": str(msg["content"]).strip()})
    messages.append({"role": "user", "content": query.strip()})

    search_used = False
    last_exc: Optional[Exception] = None

    for retry_round in range(2):
        for provider in providers_to_try:
            if provider == "gemini":
                try:
                    g_model = (os.getenv("GEMINI_MODEL") or getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest").strip()
                    gemini_msgs = [m for m in messages if m["role"] != "system"]
                    ans, used_m, s_used = await gcs.call_gemini(
                        messages=gemini_msgs,
                        system_prompt=system_prompt,
                        preferred_model=g_model
                    )
                    if ans:
                        if is_time_sensitive and not s_used:
                            from app.services.web_search_service import web_search
                            w_res = await web_search(query)
                            if w_res.get("results"):
                                ans += f"\n\nSource: {w_res['results'][0]['url']}"
                        return (ans, "ai", used_m) if return_model else (ans, "ai")
                except Exception as exc:
                    last_exc = exc
                    logger.warning("[Assistant] Gemini provider attempt failed: %s", exc)
                    continue

            elif provider == "groq":
                try:
                    active_key, _, _ = groq_key_pool.get_key()
                    if not active_key:
                        continue

                    # Import groq safely
                    import groq
                    groq_client = groq.Groq(api_key=active_key)
                    models_to_try = [
                        getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile",
                        "llama-3.1-8b-instant"
                    ]

                    # Time sensitive web search injection
                    groq_messages = list(messages)
                    if is_time_sensitive:
                        from app.services.web_search_service import web_search
                        w_res = await web_search(query)
                        if w_res.get("results"):
                            search_used = True
                            snippets = [f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}" for r in w_res["results"]]
                            groq_messages[0]["content"] += f"\n\n## Web Search Live Context:\n" + "\n\n".join(snippets)

                    for model_id in models_to_try:
                        try:
                            completion = await asyncio.to_thread(
                                groq_client.chat.completions.create,
                                model=model_id,
                                messages=groq_messages,
                                temperature=0.2,
                                max_tokens=1024,
                            )
                            if completion and completion.choices:
                                ans_text = completion.choices[0].message.content.strip()
                                if search_used and 'w_res' in locals() and w_res.get("results"):
                                    top_url = w_res["results"][0]["url"]
                                    if top_url not in ans_text:
                                        ans_text += f"\n\nSource: {top_url}"
                                groq_key_pool.mark_success(active_key)
                                return (ans_text, "ai", model_id) if return_model else (ans_text, "ai")
                        except Exception as m_exc:
                            logger.warning("[Assistant] Groq model %s attempt error: %s", model_id, m_exc)
                            last_exc = m_exc
                            continue
                except Exception as g_exc:
                    last_exc = g_exc
                    logger.warning("[Assistant] Groq provider attempt failed: %s", g_exc)
                    continue

        # If rate limited, sleep briefly
        if retry_round == 0 and not force_llm:
            await asyncio.sleep(0.05 if os.getenv("PYTEST_CURRENT_TEST") else 1.0)
            groq_key_pool.clear_cooldowns()
            gemini_key_pool.clear_cooldowns()

    if force_llm:
        raise last_exc or RuntimeError("All AI providers failed in force_llm mode.")

    fallback_ans = answer_ipo_query(query, active_ipos=active_ipos, chat_history=chat_history)
    return (fallback_ans, "fallback", "rule_engine") if return_model else (fallback_ans, "fallback")


# Backward compatibility aliases
groq_answer_query = groq_answer_ipo_query
answer_portfolio_query = answer_ipo_query
