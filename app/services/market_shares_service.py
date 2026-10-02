import logging
from typing import List, Dict, Any, Optional
from app.services.market_price_service import get_live_price

logger = logging.getLogger(__name__)

# Curated list of high-conviction positional swing ideas (2–3 month investment horizon)
# Focused on fundamentally sound, large/mid-cap leaders at attractive valuations or key support zones.
VETTED_SWING_CANDIDATES = [
    {
        "symbol": "HDFCBANK",
        "company_name": "HDFC Bank Ltd",
        "sector": "Banking & Financials",
        "base_price": 721.0,
        "entry_range": "₹710 - ₹725",
        "target_price": 820.0,
        "stop_loss": 680.0,
        "horizon": "2-3 Months",
        "expected_return": "+13.5%",
        "thesis": "Trading at attractive historical price-to-book valuation; credit growth and margin expansion expected over Q3/Q4.",
        "catalyst": "Quarterly earnings delivery & steady credit deposit ratio normalization."
    },
    {
        "symbol": "NTPC",
        "company_name": "NTPC Ltd",
        "sector": "Power & Energy Infrastructure",
        "base_price": 315.0,
        "entry_range": "₹308 - ₹318",
        "target_price": 365.0,
        "stop_loss": 294.0,
        "horizon": "2-3 Months",
        "expected_return": "+15.8%",
        "thesis": "Aggressive thermal + green renewable capacity expansion with steady domestic institutional accumulation on dips.",
        "catalyst": "Green energy subsidiary listing pipeline & peak winter/industrial power demand."
    },
    {
        "symbol": "ITC",
        "company_name": "ITC Ltd",
        "sector": "FMCG & Diversified",
        "base_price": 256.0,
        "entry_range": "₹250 - ₹258",
        "target_price": 295.0,
        "stop_loss": 240.0,
        "horizon": "2-3 Months",
        "expected_return": "+15.2%",
        "thesis": "Resilient core cigarette cash flows, non-cigarette FMCG margin expansion, and attractive defensive dividend yield.",
        "catalyst": "Hotels business demerger value unlocking & festive rural consumption pickup."
    },
    {
        "symbol": "BHARTIARTL",
        "company_name": "Bharti Airtel Ltd",
        "sector": "Telecom & Digital Services",
        "base_price": 1640.0,
        "entry_range": "₹1,610 - ₹1,650",
        "target_price": 1880.0,
        "stop_loss": 1540.0,
        "horizon": "2-3 Months",
        "expected_return": "+14.6%",
        "thesis": "Industry-leading ARPU expansion from telecom tariff hikes, accelerating enterprise data growth, and strong free cash flow.",
        "catalyst": "ARPU growth compounding in consecutive quarterly results."
    },
    {
        "symbol": "PRAJIND",
        "company_name": "Praj Industries Ltd",
        "sector": "Clean Energy & Industrial Capex",
        "base_price": 630.0,
        "entry_range": "₹615 - ₹635",
        "target_price": 725.0,
        "stop_loss": 585.0,
        "horizon": "2-3 Months",
        "expected_return": "+15.0%",
        "thesis": "Global and domestic ethanol blending mandate tailwinds with robust order book in sustainable aviation fuels (SAF).",
        "catalyst": "Government policy push on 20% ethanol blending and renewable industrial orders."
    }
]


async def get_vetted_swing_shares() -> List[Dict[str, Any]]:
    """
    Fetches live market prices for vetted 2-3 month swing picks and dynamically computes entry,
    target, stop-loss levels, and upside percentages.
    """
    results = []
    for item in VETTED_SWING_CANDIDATES:
        sym = item["symbol"]
        live_price, change_pct = await get_live_price(sym, "NSE")
        current_price = live_price if (live_price and live_price > 0) else item["base_price"]

        target = round(current_price * 1.14, 1)  # ~14% target
        stop = round(current_price * 0.94, 1)    # ~6% stop loss (1:2.3 risk-reward)
        entry_low = round(current_price * 0.985, 1)
        entry_high = round(current_price * 1.01, 1)

        upside_pct = round(((target - current_price) / current_price) * 100, 1)
        downside_pct = round(((current_price - stop) / current_price) * 100, 1)

        results.append({
            "symbol": sym,
            "company_name": item["company_name"],
            "sector": item["sector"],
            "current_price": current_price,
            "entry_range": f"₹{entry_low:,.1f} - ₹{entry_high:,.1f}",
            "target_price": target,
            "stop_loss": stop,
            "upside_pct": upside_pct,
            "downside_pct": downside_pct,
            "horizon": item["horizon"],
            "thesis": item["thesis"],
            "catalyst": item["catalyst"]
        })
    return results


def format_shares_summary_card(shares: List[Dict[str, Any]]) -> str:
    """
    Formats the vetted swing ideas into a clear, attractive Telegram HTML card.
    """
    lines = [
        "🎯 <b>IPO PULSE · CURATED SWING PICKS (2–3 MONTHS)</b>",
        "<i>High-conviction positional shares with favorable risk-reward setups:</i>",
        ""
    ]

    for idx, s in enumerate(shares, 1):
        lines.append(f"<b>{idx}. {s['company_name']} ({s['symbol']})</b> · <i>{s['sector']}</i>")
        lines.append(f"   • <b>CMP:</b> ₹{s['current_price']:,.1f} | <b>Buy Zone:</b> {s['entry_range']}")
        lines.append(f"   • 🎯 <b>Target (2–3M):</b> <b>₹{s['target_price']:,.1f}</b> (+{s['upside_pct']}%)")
        lines.append(f"   • 🛑 <b>Stop-Loss:</b> ₹{s['stop_loss']:,.1f} (-{s['downside_pct']}%)")
        lines.append(f"   • 💡 <b>Thesis:</b> {s['thesis']}")
        lines.append("")

    lines.append("🛡️ <b>Risk Management Discipline:</b>")
    lines.append("• Maintain a strict stop-loss on closing basis.")
    lines.append("• Book partial profit (50%) at +10% to +12% and trail stop-loss to buy price.")
    lines.append("• Limit single-stock allocation to under 15–20% of your capital.")
    lines.append("")
    lines.append("⚡ <i>Reply with any symbol (e.g. \"HDFCBANK\") for deep fundamental analysis.</i>")

    return "\n".join(lines)
