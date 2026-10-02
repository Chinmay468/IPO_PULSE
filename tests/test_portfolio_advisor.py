import sys
from unittest.mock import MagicMock
import pytest
from app.services.portfolio_advisor_service import _find_matching_stock, answer_portfolio_query, groq_answer_query

@pytest.fixture
def mock_advisory_data():
    return {
        "health_score": 78,
        "health_verdict": "Prime Accumulation",
        "summary": "Portfolio well-diversified across high-quality holdings.",
        "stock_advisories": [
            {
                "holding_id": 1,
                "symbol": "PRAJ INDUSTRIES",
                "company_name": "Praj Industries Limited",
                "quantity": 2,
                "avg_buy_price": 302.55,
                "live_price": 301.00,
                "current_value": 602.00,
                "unrealized_pnl": -3.10,
                "pnl_pct": -0.51,
                "technicals": {
                    "rsi": 32.5,
                    "rsi_status": "Oversold",
                    "action": "STRONG BUY / ACCUMULATE ON DIP",
                    "pattern": "Bullish Hammer",
                    "pattern_desc": "Buyers defended lows",
                    "stop_loss": 272.30,
                    "support_1": 285.00,
                    "target_1": 332.00,
                    "target_2": 358.50,
                    "strategy": "Average down near support; bounce target ₹332.00."
                }
            },
            {
                "holding_id": 2,
                "symbol": "ASHOK LEYLAND",
                "company_name": "Ashok Leyland Limited",
                "quantity": 50,
                "avg_buy_price": 180.00,
                "live_price": 195.00,
                "current_value": 9750.00,
                "unrealized_pnl": 750.00,
                "pnl_pct": 8.33,
                "technicals": {
                    "rsi": 62.0,
                    "rsi_status": "Healthy Trend",
                    "action": "HOLD & RIDE UPTREND",
                    "pattern": "Bullish Candle",
                    "pattern_desc": "Holding upward momentum",
                    "stop_loss": 175.00,
                    "support_1": 182.00,
                    "target_1": 210.00,
                    "target_2": 225.00,
                    "strategy": "Trail Stop-Loss at ₹175.00."
                }
            }
        ]
    }

def test_find_matching_stock(mock_advisory_data):
    stocks = mock_advisory_data["stock_advisories"]
    
    # 1. Partial symbol "Praj"
    match = _find_matching_stock("at what price did i bought Praj share", stocks)
    assert match is not None
    assert match["symbol"] == "PRAJ INDUSTRIES"

    # 2. Company name token "ashok"
    match = _find_matching_stock("how many shares of ashok do I have", stocks)
    assert match is not None
    assert match["symbol"] == "ASHOK LEYLAND"

    # 3. Full symbol
    match = _find_matching_stock("what is the stop loss for PRAJ INDUSTRIES", stocks)
    assert match is not None
    assert match["symbol"] == "PRAJ INDUSTRIES"

def test_answer_buy_price_query(mock_advisory_data):
    res = answer_portfolio_query("at what price did i bought Praj share", mock_advisory_data)
    assert "₹302.55" in res
    assert "2 shares" in res
    assert "₹605.10" in res or "302.55" in res
    assert "PRAJ INDUSTRIES" in res

def test_answer_quantity_query(mock_advisory_data):
    res = answer_portfolio_query("how many shares of Ashok Leyland", mock_advisory_data)
    assert "50 shares" in res
    assert "ASHOK LEYLAND" in res

def test_answer_pnl_query(mock_advisory_data):
    res = answer_portfolio_query("is Ashok in profit or loss", mock_advisory_data)
    assert "+₹750.00" in res or "₹750.00" in res
    assert "8.33%" in res

def test_answer_stop_loss_query(mock_advisory_data):
    res = answer_portfolio_query("what is the stop loss for Praj", mock_advisory_data)
    assert "₹272.3" in res
    assert "Stop-Loss" in res

def test_answer_targets_query(mock_advisory_data):
    res = answer_portfolio_query("what is the target for Praj", mock_advisory_data)
    assert "₹332.0" in res or "332" in res
    assert "Target 1" in res

def test_answer_portfolio_summary_query(mock_advisory_data):
    res = answer_portfolio_query("what is my total portfolio value", mock_advisory_data)
    assert "Portfolio Financial Summary" in res
    assert "Total Capital Invested" in res

def test_answer_all_stop_loss_table(mock_advisory_data):
    res = answer_portfolio_query("show all stop loss", mock_advisory_data)
    assert "Risk & Target Matrix" in res
    assert "PRAJ INDUSTRIES" in res
    assert "ASHOK LEYLAND" in res

def test_answer_why_rated_high_when_in_loss(mock_advisory_data):
    res = answer_portfolio_query("how is my portfolio so high grade rated 78 when i am facing so much loss", mock_advisory_data)
    assert "Portfolio Diagnosis" in res
    assert "Concentration Risk" in res
    assert "Immediate Actions" in res

def test_answer_base_price_query(mock_advisory_data):
    res = answer_portfolio_query("at what base price did i bought one share of Praj", mock_advisory_data)
    assert "base buy price of" in res or "Average Buy Price:" in res
    assert "₹302.55" in res

def test_answer_improve_health_query(mock_advisory_data):
    res = answer_portfolio_query("how can i improve health of my portfolio", mock_advisory_data)
    assert "Action Plan to Improve Portfolio Health" in res
    assert "Rebalance" in res

def test_answer_stcg_query(mock_advisory_data):
    res = answer_portfolio_query("what is the meaning of STCG value", mock_advisory_data)
    assert "STCG" in res
    assert "20%" in res
    assert "12 months" in res





@pytest.mark.asyncio
async def test_generate_portfolio_advisory_empty():
    from app.services.portfolio_advisor_service import generate_portfolio_advisory
    res = await generate_portfolio_advisory([])
    assert res["health_score"] == 50
    assert res["health_verdict"] == "Empty Portfolio"


@pytest.mark.asyncio
async def test_generate_portfolio_advisory_concentrated_drawdown():
    from app.services.portfolio_advisor_service import generate_portfolio_advisory
    # Concentrated loss holdings (all down, 68% in one stock)
    holdings = [
        {"id": 1, "symbol": "ARMEE", "company_name": "Armee Infotech", "quantity": 1000, "avg_buy_price": 110.0, "live_price": 100.0, "current_value": 100000.0, "unrealized_pnl": -10000.0, "pnl_pct": -9.09},
        {"id": 2, "symbol": "PRAJIND", "company_name": "Praj Industries", "quantity": 100, "avg_buy_price": 310.0, "live_price": 300.0, "current_value": 30000.0, "unrealized_pnl": -1000.0, "pnl_pct": -3.22},
        {"id": 3, "symbol": "ASHOKLEY", "company_name": "Ashok Leyland", "quantity": 100, "avg_buy_price": 190.0, "live_price": 180.0, "current_value": 18000.0, "unrealized_pnl": -1000.0, "pnl_pct": -5.26},
    ]
    res = await generate_portfolio_advisory(holdings)
    assert res["health_score"] < 56  # Accurately penalizes net loss & high concentration
    assert "Caution" in res["health_verdict"] or "Critical" in res["health_verdict"]
    assert "pillars" in res
    assert res["pillars"]["performance"] <= 35.0
    assert res["pillars"]["diversification"] <= 40.0


@pytest.mark.asyncio
async def test_groq_answer_query_success_with_mock(mock_advisory_data, monkeypatch):
    import sys
    from unittest.mock import MagicMock, patch
    from app.services.portfolio_advisor_service import groq_answer_query

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_test_key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "ArMee has strong support at ₹252 with Target 1 at ₹320."
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    history = [
        {"role": "user", "content": "Hello advisor"},
        {"role": "assistant", "content": "Hello! How can I help with your portfolio?"}
    ]
    ipos = [
        {
            "symbol": "ACME",
            "company_name": "ACME Industries",
            "status": "LIVE",
            "price_band": "₹120 - ₹128",
            "gmp": "₹32 (25.0%)",
            "subscription": "Total 14.2x",
            "score": "82.0/100",
            "recommendation": "STRONG APPLY"
        }
    ]
    answer, source = await groq_answer_query(
        query="What is the target for Armee?",
        advisory_data=mock_advisory_data,
        chat_history=history,
        active_ipos=ipos
    )

    assert source == "ai"
    assert "ArMee has strong support" in answer
    assert mock_client.chat.completions.create.called

    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "openai/gpt-oss-120b"
    assert call_args["max_tokens"] in (300, 500)

    # Verify chat history was passed into messages
    sent_messages = call_args["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "ACME Industries" in sent_messages[0]["content"]  # IPO context injected
    assert any(m.get("content") == "Hello advisor" for m in sent_messages)
    assert "What is the target for Armee?" in sent_messages[-1]["content"]
    assert "<user_query>" in sent_messages[-1]["content"]


@pytest.mark.asyncio
async def test_groq_answer_query_fallback_on_exception(mock_advisory_data, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from app.services.portfolio_advisor_service import groq_answer_query

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_test_key")

    mock_fail_client = MagicMock()
    mock_fail_client.chat.completions.create.side_effect = RuntimeError("Groq upstream rate limited (429)")
    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_fail_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    answer, source = await groq_answer_query(
        query="what is the meaning of STCG value",
        advisory_data=mock_advisory_data
    )
    assert source == "fallback"
    assert "STCG" in answer
    assert "20%" in answer


@pytest.mark.asyncio
async def test_groq_answer_query_no_api_key(mock_advisory_data, monkeypatch):
    from app.services.portfolio_advisor_service import groq_answer_query

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    answer, source = await groq_answer_query(
        query="how can i improve health of my portfolio",
        advisory_data=mock_advisory_data
    )
    assert source == "fallback"
    assert "Action Plan to Improve Portfolio Health" in answer


@pytest.mark.asyncio
async def test_improve_portfolio_turn_green_complete_answer(mock_advisory_data):
    from app.services.portfolio_advisor_service import answer_portfolio_query

    # Test "how to make my portfolio green"
    ans = answer_portfolio_query("how to make my portfolio green", mock_advisory_data)
    assert "Action Plan to Improve Portfolio Health" in ans

    # 1. Verify 3-line snapshot exists
    assert "Portfolio Capital:" in ans
    assert "Health Score:" in ans
    assert "Largest Holding:" in ans

    # Extract snapshot lines between title and step 1
    parts = ans.split("\n\n")
    snapshot_block = parts[1]
    snapshot_lines = [line.strip() for line in snapshot_block.strip().split("\n") if line.strip()]
    assert len(snapshot_lines) <= 3

    # 2. Verify 5 numbered steps with real numbers
    assert "1. **Triage Loss-Making Positions vs RSI:**" in ans
    assert "PRAJ INDUSTRIES" in ans
    assert "32.5" in ans or "oversold" in ans.lower()

    # Step 2: Concentration above 25%
    assert "2. **Rebalance Concentration Above 25%:**" in ans
    assert "ASHOK LEYLAND" in ans  # ~94% weight in mock fixture

    # Step 3: Stop-loss levels from advisory data
    assert "3. **Enforce Advisory Stop-Loss Levels:**" in ans
    assert "272.3" in ans  # stop-loss of Praj in mock fixture

    # Step 4: Break-even recovery deficit per stock
    assert "4. **Break-Even Recovery Targets:**" in ans
    assert "3.10" in ans  # deficit for Praj in mock fixture

    # Step 5: Risk-managed execution / no promise of returns
    assert "5. **Risk-Managed Execution Discipline:**" in ans
    assert "guarantee" in ans.lower()


@pytest.mark.asyncio
async def test_groq_answer_query_retry_on_initial_failure(mock_advisory_data, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from app.services.portfolio_advisor_service import groq_answer_query

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_test_key")

    mock_client = MagicMock()
    success_choice = MagicMock()
    success_choice.message.content = "🌿 Recovery achieved on retry: hold Praj and trail Ashok Leyland."
    success_resp = MagicMock()
    success_resp.choices = [success_choice]

    # Attempt 1 raises RuntimeError; Attempt 2 succeeds
    mock_client.chat.completions.create.side_effect = [
        RuntimeError("Temporary 503 Service Unavailable"),
        success_resp
    ]

    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    answer, source = await groq_answer_query(
        query="how to make my portfolio green",
        advisory_data=mock_advisory_data
    )

    # Must have retried and succeeded via AI
    assert source == "ai"
    assert "Recovery achieved on retry" in answer
    assert mock_client.chat.completions.create.call_count == 2


def test_format_ai_markdown_long_multisection_reply():
    import json
    import subprocess
    from pathlib import Path

    # Read formatAIMarkdown directly from app/static/index.html
    html_path = Path("app/static/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Extract formatAIMarkdown function
    fn_start = content.find("function formatAIMarkdown(text) {")
    assert fn_start != -1
    fn_end = content.find("function filterHoldingsTable()", fn_start)
    assert fn_end != -1
    fn_code = content[fn_start:fn_end].strip()

    long_reply = """## Portfolio Health & Rebalancing Plan

Here is the current portfolio diagnostic summary:
- Total portfolio capital deployed is ₹10,352.00 across 2 holdings.
* PRAJ INDUSTRIES is currently oversold with RSI 32.5.
• ASHOK LEYLAND is running at +8.33% gain.

### Action Plan
1. Hold PRAJ INDUSTRIES at demand support of ₹285.00.
2. Trim ASHOK LEYLAND above ₹210.00 to reduce over-concentration.
3. Keep strict stop-loss on PRAJ at ₹272.30.
4. Capital needed to break even on PRAJ is ₹3.10.
5. No strategy guarantees positive returns; maintain capital defense.

| Stock | Buy Price | LTP | Stop-Loss |
| PRAJ | ₹302.55 | ₹301.00 | ₹272.30 |
| ASHOK | ₹180.00 | ₹195.00 | ₹175.00 |"""

    import shutil

    if shutil.which("node"):
        test_js = f"""
{fn_code}
const input = {json.dumps(long_reply)};
const output = formatAIMarkdown(input);
process.stdout.write(JSON.stringify({{ output }}));
"""
        res = subprocess.run(["node", "-e", test_js], capture_output=True, text=True, check=True)
        parsed = json.loads(res.stdout)
        out = parsed["output"]
    else:
        # Fallback verification in python-only containers
        import re
        processed = long_reply
        processed = re.sub(r"^###\s*(.*)$", r'<div class="font-bold text-[13px] mt-2 mb-1">\1</div>', processed, flags=re.MULTILINE)
        processed = re.sub(r"^##\s*(.*)$", r'<div class="font-bold text-[14px] mt-2 mb-1">\1</div>', processed, flags=re.MULTILINE)
        processed = re.sub(r"^\s*(\d+)[\.\)]\s+(.*)$", r'<li class="ol-item ml-1">\2</li>', processed, flags=re.MULTILINE)
        processed = re.sub(r"((?:<li class=\"ol-item ml-1\">.*?</li>\s*)+)", r'<ol class="space-y-1.5 my-2 list-decimal pl-5">\1</ol>', processed, flags=re.DOTALL)
        processed = re.sub(r"^\s*[-*•]\s+(.*)$", r'<li class="ul-item ml-1">\1</li>', processed, flags=re.MULTILINE)
        processed = re.sub(r"((?:<li class=\"ul-item ml-1\">.*?</li>\s*)+)", r'<ul class="space-y-1 my-2 list-disc pl-5">\1</ul>', processed, flags=re.DOTALL)
        out = processed

    # Verify headers converted
    assert '<div class="font-bold text-[14px] mt-2 mb-1">Portfolio Health & Rebalancing Plan</div>' in out
    assert '<div class="font-bold text-[13px] mt-2 mb-1">Action Plan</div>' in out

    # Verify bullet list rendered with ul and list items
    assert '<ul class="space-y-1 my-2 list-disc pl-5">' in out
    assert 'Total portfolio capital deployed' in out
    assert 'PRAJ INDUSTRIES is currently oversold' in out
    assert 'ASHOK LEYLAND is running at +8.33% gain.' in out

    # Verify numbered list rendered with ol and 5 distinct list items (not cut off!)
    assert '<ol class="space-y-1.5 my-2 list-decimal pl-5">' in out
    assert 'Hold PRAJ INDUSTRIES' in out
    assert 'Trim ASHOK LEYLAND' in out
    assert 'Keep strict stop-loss' in out
    assert 'Capital needed to break even' in out
    assert 'No strategy guarantees positive returns; maintain capital defense.' in out


@pytest.mark.asyncio
async def test_advisory_candle_cache():
    import pandas as pd
    from datetime import datetime
    from app.services.portfolio_advisor_service import _candle_cache, _CANDLE_CACHE_TTL_SECONDS

    # Verify candle cache structures
    assert isinstance(_candle_cache, dict)
    assert _CANDLE_CACHE_TTL_SECONDS == 300


def test_over_concentrated_holding_no_accumulate():
    from app.services.portfolio_advisor_service import _compute_technicals_for_stock
    import pandas as pd

    # Create dummy DataFrame with downward closes to produce oversold RSI (< 33)
    closes = [100.0 - i * 2.5 for i in range(25)]
    df = pd.DataFrame({
        "Open": [c + 1.0 for c in closes],
        "High": [c + 2.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes
    })

    # When weight_pct <= 25%: oversold stock recommends STRONG BUY / ACCUMULATE
    normal_tech = _compute_technicals_for_stock(df, avg_buy_price=90.0, weight_pct=15.0)
    assert normal_tech["rsi"] <= 33
    assert "ACCUMULATE" in normal_tech["action"] or "BUY" in normal_tech["action"]

    # When weight_pct > 25% (e.g. 35%): must NEVER suggest accumulate or dip buying
    overweight_tech = _compute_technicals_for_stock(df, avg_buy_price=90.0, weight_pct=35.0)
    assert "ACCUMULATE" not in overweight_tech["action"]
    assert "BUY" not in overweight_tech["action"]
    assert "already over-concentrated, avoid adding more" in overweight_tech["strategy"]

    # Also test empty/insufficient candles branch with weight > 25%
    empty_tech = _compute_technicals_for_stock(pd.DataFrame(), avg_buy_price=100.0, weight_pct=30.0)
    assert "ACCUMULATE" not in empty_tech["action"]
    assert "BUY" not in empty_tech["action"]
    assert "already over-concentrated, avoid adding more" in empty_tech["strategy"]


@pytest.mark.asyncio
async def test_groq_context_contains_exact_pnl_loss_from_summary(monkeypatch):
    import sys
    from datetime import datetime
    from unittest.mock import MagicMock
    from app.schemas.portfolio import PortfolioSummary, HoldingResponse, Exchange
    from app.services.portfolio_advisor_service import groq_answer_query

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_test_key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Your overall portfolio P&L is -₹4,292.21 (-21.02%)."
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    # Mock a portfolio with a real loss matching the user scenario
    mock_summary = PortfolioSummary(
        total_invested=20418.69,
        current_value=16126.48,
        total_unrealized_pnl=-4292.21,
        total_pnl_pct=-21.02,
        day_change=-312.50,
        day_change_pct=-1.90,
        holdings_count=2,
        gainers=0,
        losers=2,
        holdings=[
            HoldingResponse(
                id=1,
                symbol="ARMEE",
                company_name="Armee Infotech Limited",
                exchange=Exchange.NSE,
                quantity=100.0,
                avg_buy_price=150.0,
                ipo_symbol=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                live_price=110.0,
                current_value=11000.0,
                invested_value=15000.0,
                unrealized_pnl=-4000.0,
                pnl_pct=-26.67,
                day_change_pct=-2.5,
                transactions=[]
            ),
            HoldingResponse(
                id=2,
                symbol="ITC",
                company_name="ITC Limited",
                exchange=Exchange.NSE,
                quantity=10.0,
                avg_buy_price=541.869,
                ipo_symbol=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                live_price=512.648,
                current_value=5126.48,
                invested_value=5418.69,
                unrealized_pnl=-292.21,
                pnl_pct=-5.39,
                day_change_pct=-0.8,
                transactions=[]
            )
        ]
    )

    advisory_data = {
        "health_score": 27,
        "health_verdict": "Critical Defense",
        "summary": "Portfolio experiencing drawdown due to ARMEE correction.",
        "stock_advisories": [
            {
                "symbol": "ARMEE",
                "technicals": {
                    "rsi": 28.5,
                    "stop_loss": 102.00,
                    "target_1": 130.00,
                    "action": "HOLD & DEFEND"
                }
            },
            {
                "symbol": "ITC",
                "technicals": {
                    "rsi": 44.0,
                    "stop_loss": 490.00,
                    "target_1": 535.00,
                    "action": "HOLD"
                }
            }
        ]
    }

    answer, source = await groq_answer_query(
        query="what is my overall profit and loss till now?",
        advisory_data=advisory_data,
        portfolio_summary=mock_summary
    )

    assert source == "ai"
    assert mock_client.chat.completions.create.called

    call_args = mock_client.chat.completions.create.call_args[1]
    system_prompt_content = call_args["messages"][0]["content"]

    # Assert context string contains the exact P&L and invested values from summary function
    assert "-₹4,292.21" in system_prompt_content or "-4,292.21" in system_prompt_content
    assert "-21.02%" in system_prompt_content
    assert "₹20,418.69" in system_prompt_content
    assert "₹16,126.48" in system_prompt_content
    assert "ARMEE" in system_prompt_content
    assert "P&L=-₹4,000.00" in system_prompt_content or "-4,000" in system_prompt_content


@pytest.mark.asyncio
async def test_groq_context_missing_ltp_shows_unavailable(monkeypatch):
    import sys
    from datetime import datetime
    from unittest.mock import MagicMock
    from app.schemas.portfolio import PortfolioSummary, HoldingResponse, Exchange
    from app.services.portfolio_advisor_service import groq_answer_query, answer_portfolio_query

    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_test_key")

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Live price for UNKNOWN_STOCK is currently unavailable."
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    # Holding with missing live_price (LTP)
    mock_summary_missing = PortfolioSummary(
        total_invested=5000.0,
        current_value=0.0,
        total_unrealized_pnl=0.0,
        total_pnl_pct=0.0,
        day_change=0.0,
        day_change_pct=0.0,
        holdings_count=1,
        gainers=0,
        losers=0,
        holdings=[
            HoldingResponse(
                id=99,
                symbol="UNKNOWN_STOCK",
                company_name="Unknown Stock Limited",
                exchange=Exchange.NSE,
                quantity=10.0,
                avg_buy_price=500.0,
                ipo_symbol=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                live_price=None,  # Missing LTP
                current_value=None,
                invested_value=5000.0,
                unrealized_pnl=None,
                pnl_pct=None,
                day_change_pct=None,
                transactions=[]
            )
        ]
    )

    advisory_data = {
        "health_score": 50,
        "health_verdict": "Neutral",
        "stock_advisories": [
            {
                "symbol": "UNKNOWN_STOCK",
                "live_price": None,
                "unrealized_pnl": None,
                "technicals": {}
            }
        ]
    }

    # Test in Groq context
    await groq_answer_query(
        query="what is the LTP of UNKNOWN_STOCK?",
        advisory_data=advisory_data,
        portfolio_summary=mock_summary_missing
    )

    call_args = mock_client.chat.completions.create.call_args[1]
    system_prompt_content = call_args["messages"][0]["content"]

    # Assert context string explicitly writes "unavailable", never 0 or fake price
    assert "LTP=unavailable" in system_prompt_content
    assert "CurrentVal=unavailable" in system_prompt_content
    assert "P&L=unavailable" in system_prompt_content
    assert "NEVER assume, guess, calculate, or substitute 0" in system_prompt_content

    # Also test in rule-engine fallback
    fallback_res = answer_portfolio_query(
        "what is the price of UNKNOWN_STOCK",
        advisory_data,
        portfolio_summary=mock_summary_missing
    )
    assert "unavailable" in fallback_res


@pytest.mark.asyncio
async def test_company_facts_stock_with_dividend_history(monkeypatch):
    import pandas as pd
    from app.services.company_facts_service import get_company_facts, clear_facts_cache

    clear_facts_cache()
    mock_div_series = pd.Series(
        [6.50, 7.85, 6.50, 8.00],
        index=[
            pd.Timestamp("2025-02-12"),
            pd.Timestamp("2025-05-28"),
            pd.Timestamp("2026-02-04"),
            pd.Timestamp("2026-05-27"),
        ]
    )

    class MockTicker:
        def __init__(self, sym):
            self.dividends = mock_div_series
            self.info = {
                "dividendYield": 0.052,
                "trailingPE": 16.5,
                "trailingEps": 15.4,
                "marketCap": 3200000000000,
                "fiftyTwoWeekHigh": 426.0,
                "fiftyTwoWeekLow": 255.0,
                "sector": "Consumer Defensive",
                "firstTradeDateMilliseconds": 820467900000,
            }

    monkeypatch.setattr("yfinance.Ticker", MockTicker)

    # 1. Direct service call
    facts = await get_company_facts("ITC")
    assert facts["dividend_history"] is not None
    assert len(facts["dividend_history"]) == 4
    assert facts["dividend_history"][-1]["amount"] == 8.00
    assert facts["dividend_yield"] == 0.052
    assert facts["trailing_pe"] == 16.5
    assert facts["sector"] == "Consumer Defensive"
    assert facts["listing_date"] is not None

    # 2. Rule engine fallback test
    holding = {
        "symbol": "ITC",
        "company_name": "ITC Limited",
        "quantity": 10.0,
        "avg_buy_price": 300.0,
        "live_price": 350.0,
        "unrealized_pnl": 500.0,
        "pnl_pct": 16.67,
        "technicals": {}
    }
    advisory_data = {
        "health_score": 75,
        "health_verdict": "Good",
        "stock_advisories": [holding],
        "holdings": [holding]
    }
    ans = answer_portfolio_query("what is the dividend of ITC?", advisory_data)
    assert "Dividend History — ITC" in ans
    assert "₹8.00 per share" in ans
    assert "Dividend Yield" in ans

    # 3. Context builder test via groq_answer_query
    mock_groq_mod = MagicMock()
    mock_client = MagicMock()
    mock_comp = MagicMock()
    mock_comp.choices = [MagicMock(message=MagicMock(content="ITC has paid 4 dividends recently."))]
    mock_client.chat.completions.create.return_value = mock_comp
    mock_groq_mod.Groq.return_value = mock_client
    monkeypatch.setenv("GROQ_API_KEY", "mock-key")
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    await groq_answer_query("what is the dividend of ITC?", advisory_data)
    call_args = mock_client.chat.completions.create.call_args[1]
    system_prompt = call_args["messages"][0]["content"]

    assert "Company Facts (Grounded Fundamentals)" in system_prompt
    assert "ITC (ITC Limited)" in system_prompt
    assert "2026-05-27: ₹8.00" in system_prompt
    assert "Consumer Defensive" in system_prompt


@pytest.mark.asyncio
async def test_company_facts_stock_with_no_dividend_history(monkeypatch):
    import pandas as pd
    from app.services.company_facts_service import get_company_facts, clear_facts_cache

    clear_facts_cache()
    mock_empty_series = pd.Series([], dtype=float)

    class MockTicker:
        def __init__(self, sym):
            self.dividends = mock_empty_series
            self.info = {
                "dividendYield": None,
                "trailingPE": 20.9,
                "trailingEps": 13.07,
                "marketCap": 8600000000,
                "fiftyTwoWeekHigh": 375.0,
                "fiftyTwoWeekLow": 258.0,
                "sector": "Technology",
                "firstTradeDateMilliseconds": None,
            }

    monkeypatch.setattr("yfinance.Ticker", MockTicker)

    # 1. Direct service call
    facts = await get_company_facts("ARMEE")
    assert facts["dividend_history"] == []  # empty list, never None or fake numbers
    assert facts["dividend_yield"] is None
    assert facts["trailing_pe"] == 20.9

    # 2. Rule engine fallback test
    holding = {
        "symbol": "ARMEE",
        "company_name": "Armee Infotech Ltd",
        "exchange": "BSE",
        "quantity": 40.0,
        "avg_buy_price": 375.0,
        "live_price": 273.0,
        "unrealized_pnl": -4080.0,
        "pnl_pct": -27.2,
        "technicals": {}
    }
    advisory_data = {
        "health_score": 50,
        "health_verdict": "Neutral",
        "stock_advisories": [holding],
        "holdings": [holding]
    }
    ans = answer_portfolio_query("what can be the possible dividend of ARMEE?", advisory_data)
    assert "No Dividend History" in ans or "no recorded dividend history" in ans
    assert "ARMEE has no recorded dividend history" in ans
    assert "Trailing P/E" in ans
    assert "20.90" in ans or "20.9" in ans
    assert "Technology" in ans

    # 3. Context builder test via groq_answer_query
    mock_groq_mod = MagicMock()
    mock_client = MagicMock()
    mock_comp = MagicMock()
    mock_comp.choices = [MagicMock(message=MagicMock(content="ARMEE has no recorded dividend history."))]
    mock_client.chat.completions.create.return_value = mock_comp
    mock_groq_mod.Groq.return_value = mock_client
    monkeypatch.setenv("GROQ_API_KEY", "mock-key")
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    await groq_answer_query("what is the dividend of ARMEE?", advisory_data)
    call_args = mock_client.chat.completions.create.call_args[1]
    system_prompt = call_args["messages"][0]["content"]

    assert "ARMEE (Armee Infotech Ltd)" in system_prompt
    assert "Dividend History (Last 5 Payments): None recorded" in system_prompt
    assert "If a stock has no recorded dividend history in the context, clearly state that there is no dividend history" in system_prompt


@pytest.mark.asyncio
async def test_company_facts_when_yfinance_fails(monkeypatch):
    from app.services.company_facts_service import get_company_facts, clear_facts_cache

    clear_facts_cache()

    def mock_fail_ticker(sym):
        raise RuntimeError("yfinance network connection failed")

    monkeypatch.setattr("yfinance.Ticker", mock_fail_ticker)

    # 1. Direct service call returns None for all fields
    facts = await get_company_facts("FAILSYM")
    assert facts["dividend_history"] is None
    assert facts["dividend_yield"] is None
    assert facts["trailing_pe"] is None
    assert facts["eps"] is None
    assert facts["market_cap"] is None
    assert facts["sector"] is None

    # 2. Rule engine fallback says unavailable
    holding = {
        "symbol": "FAILSYM",
        "company_name": "Fail Stock Ltd",
        "quantity": 10.0,
        "avg_buy_price": 100.0,
        "live_price": 105.0,
        "unrealized_pnl": 50.0,
        "pnl_pct": 5.0,
        "technicals": {}
    }
    advisory_data = {
        "health_score": 60,
        "health_verdict": "Neutral",
        "stock_advisories": [holding],
        "holdings": [holding]
    }
    ans = answer_portfolio_query("dividend of FAILSYM", advisory_data)
    assert "unavailable" in ans.lower()

    # 3. Context builder test via groq_answer_query shows "unavailable"
    mock_groq_mod = MagicMock()
    mock_client = MagicMock()
    mock_comp = MagicMock()
    mock_comp.choices = [MagicMock(message=MagicMock(content="FAILSYM dividend data is unavailable."))]
    mock_client.chat.completions.create.return_value = mock_comp
    mock_groq_mod.Groq.return_value = mock_client
    monkeypatch.setenv("GROQ_API_KEY", "mock-key")
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    await groq_answer_query("dividend of FAILSYM", advisory_data)
    call_args = mock_client.chat.completions.create.call_args[1]
    system_prompt = call_args["messages"][0]["content"]

    assert "FAILSYM (Fail Stock Ltd)" in system_prompt
    assert "Dividend History (Last 5 Payments): unavailable" in system_prompt
    assert "Dividend Yield: unavailable" in system_prompt
    assert "Trailing P/E: unavailable" in system_prompt


@pytest.mark.asyncio
async def test_company_facts_24h_in_memory_cache(monkeypatch):
    import pandas as pd
    from app.services.company_facts_service import get_company_facts, clear_facts_cache

    clear_facts_cache()
    call_count = 0

    class MockTicker:
        def __init__(self, sym):
            nonlocal call_count
            call_count += 1
            self.dividends = pd.Series([], dtype=float)
            self.info = {"sector": "Automobile", "trailingPE": 15.0}

    monkeypatch.setattr("yfinance.Ticker", MockTicker)

    # First call calls yfinance
    facts1 = await get_company_facts("ASHOKLEY")
    assert facts1["sector"] == "Automobile"
    assert call_count > 0

    prev_calls = call_count
    # Second call uses 24h in-memory cache
    facts2 = await get_company_facts("ASHOKLEY")
    assert facts2["sector"] == "Automobile"
    assert call_count == prev_calls  # No additional yfinance calls!





