import sys
import pytest
import httpx
from unittest.mock import MagicMock
from app.services.gemini_client_service import (
    call_gemini,
    get_gemini_api_key,
    GEMINI_SEARCH_TOOLS,
)
from app.services.portfolio_advisor_service import groq_answer_query


def test_get_gemini_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert get_gemini_api_key() is None

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    assert get_gemini_api_key() == "test-gemini-key"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    assert get_gemini_api_key() == "test-google-key"


@pytest.mark.asyncio
async def test_call_gemini_direct_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")

    def mock_gemini_transport(request: httpx.Request) -> httpx.Response:
        assert "models/gemini" in str(request.url)
        return httpx.Response(
            status_code=200,
            json={
                "candidates": [{
                    "content": {
                        "parts": [{"text": "PRAJ INDUSTRIES is a strong green energy holding."}],
                        "role": "model"
                    },
                    "finishReason": "STOP"
                }]
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_gemini_transport)) as client:
        messages = [{"role": "user", "content": "Tell me about Praj"}]
        answer, used_model, search_used = await call_gemini(
            messages=messages,
            system_prompt="You are a financial advisor.",
            client=client
        )
        assert "PRAJ INDUSTRIES" in answer
        assert not search_used
        assert "gemini" in used_model


@pytest.mark.asyncio
async def test_call_gemini_with_web_search_tool(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")

    call_count = 0

    def mock_gemini_tool_transport(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Model asks to call web_search
            return httpx.Response(
                status_code=200,
                json={
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "functionCall": {
                                    "name": "web_search",
                                    "args": {"query": "current RBI repo rate"}
                                },
                                "thoughtSignature": "test_thought_signature"
                            }],
                            "role": "model"
                        }
                    }]
                }
            )
        else:
            # Follow-up turn synthesizes answer
            return httpx.Response(
                status_code=200,
                json={
                    "candidates": [{
                        "content": {
                            "parts": [{"text": "The current RBI repo rate is 6.50%."}],
                            "role": "model"
                        }
                    }]
                }
            )

    async def mock_web_search(q):
        return {
            "query": q,
            "results": [{"title": "RBI Rate", "url": "https://rbi.org.in", "snippet": "Repo rate is 6.50%"}],
            "official_site": "rbi.org.in"
        }

    monkeypatch.setattr("app.services.web_search_service.web_search", mock_web_search)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_gemini_tool_transport)) as client:
        messages = [{"role": "user", "content": "What is RBI repo rate?"}]
        answer, used_model, search_used = await call_gemini(
            messages=messages,
            system_prompt="You are a financial advisor.",
            client=client
        )
        assert "6.50%" in answer
        assert search_used
        assert call_count == 2


@pytest.mark.asyncio
async def test_smart_shift_gemini_to_groq(monkeypatch):
    """When Gemini returns an error (e.g. 503 or 429), smart shift to Groq."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")
    monkeypatch.setenv("PRIMARY_LLM_PROVIDER", "gemini")

    # Mock call_gemini to fail
    async def mock_fail_gemini(*args, **kwargs):
        raise RuntimeError("Gemini 503 Service Unavailable")

    monkeypatch.setattr("app.services.gemini_client_service.call_gemini", mock_fail_gemini)

    # Mock Groq to succeed
    mock_client = MagicMock()
    success_choice = MagicMock()
    success_choice.message.content = "Groq succeeded after Gemini smart shift."
    success_resp = MagicMock()
    success_resp.choices = [success_choice]
    mock_client.chat.completions.create.return_value = success_resp

    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")

    mock_advisory = {
        "health_score": 75,
        "health_verdict": "Good",
        "holdings": []
    }

    answer, source, model = await groq_answer_query(
        query="how is my portfolio",
        advisory_data=mock_advisory,
        return_model=True
    )
    assert source == "ai"
    assert "Groq succeeded after Gemini smart shift" in answer


@pytest.mark.asyncio
async def test_smart_shift_groq_to_gemini(monkeypatch):
    """When Groq fails and primary is groq, smart shift to Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake_gemini_key")
    monkeypatch.setenv("PRIMARY_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")

    # Mock Groq to fail
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("Groq 429 Rate Limit Exceeded")
    mock_groq_mod = MagicMock()
    mock_groq_mod.Groq = MagicMock(return_value=mock_client)
    monkeypatch.setitem(sys.modules, "groq", mock_groq_mod)

    # Mock Gemini to succeed
    async def mock_success_gemini(*args, **kwargs):
        return "Gemini succeeded after Groq 429 smart shift.", "gemini-3.1-flash-lite", False

    monkeypatch.setattr("app.services.gemini_client_service.call_gemini", mock_success_gemini)

    mock_advisory = {
        "health_score": 75,
        "health_verdict": "Good",
        "holdings": []
    }

    answer, source, model = await groq_answer_query(
        query="how is my portfolio",
        advisory_data=mock_advisory,
        return_model=True
    )
    assert source == "ai"
    assert "Gemini succeeded after Groq 429" in answer
    assert "gemini" in model
