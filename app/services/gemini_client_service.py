import os
import json
import logging
import asyncio
from typing import Optional, Any
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GEMINI_SEARCH_TOOLS = [{
    "function_declarations": [{
        "name": "web_search",
        "description": "Search official regulatory sites (SEBI, NSE, BSE, RBI) and reputable Indian finance media for live time-sensitive financial facts, officeholders, index levels, interest rates, or rules.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The search query for live time-sensitive facts."
                }
            },
            "required": ["query"]
        }
    }]
}]


import re
import time


def get_all_gemini_api_keys() -> list[str]:
    """
    Discovers all configured Gemini / Google API keys from environment variables,
    settings, and .env file. Supports GEMINI_API_KEY, GOOGLE_API_KEY, etc.
    Deduplicates and preserves discovery order. Never logs key contents.
    """
    raw_candidates = []

    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3", "GEMINI_API_KEYS", "GOOGLE_API_KEYS"):
        v = os.getenv(name) or (getattr(settings, name, "") if settings else "") or ""
        if v and isinstance(v, str):
            raw_candidates.append(v)

    for env_name, env_val in os.environ.items():
        u = env_name.upper()
        if (u.startswith("GEMINI_") or u.startswith("GOOGLE_")) and "KEY" in u:
            if env_val and isinstance(env_val, str) and env_val.strip():
                raw_candidates.append(env_val.strip())

    # Only load from .env file if no candidate keys were found in os.environ/settings and not running tests
    if not raw_candidates and not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            import dotenv
            if os.path.exists(".env"):
                env_map = dotenv.dotenv_values(".env")
                for k, val in env_map.items():
                    u = k.upper()
                    if (u.startswith("GEMINI_") or u.startswith("GOOGLE_")) and "KEY" in u:
                        if val and isinstance(val, str) and val.strip():
                            raw_candidates.append(val.strip())
        except Exception:
            pass

    parsed_keys: list[str] = []
    seen: set[str] = set()

    for item in raw_candidates:
        if not item:
            continue
        parts = re.split(r"[,;\n\r]+", str(item))
        for p in parts:
            clean = p.strip().strip("'\"")
            if clean and clean not in seen and len(clean) >= 15:
                parsed_keys.append(clean)
                seen.add(clean)

    return parsed_keys


from app.services.key_pool_base import BaseKeyPool


class GeminiKeyPool(BaseKeyPool):
    """
    Smart switching pool for Gemini API keys.
    Rotates keys seamlessly with cooldown tracking for rate limits.
    """
    def __init__(self):
        super().__init__(key_getter=get_all_gemini_api_keys, provider_name="Gemini")


gemini_key_pool = GeminiKeyPool()


def get_gemini_api_key() -> Optional[str]:
    """Retrieve Gemini API key from environment or app settings."""
    env_keys = [
        os.getenv("GEMINI_API_KEY"),
        os.getenv("GOOGLE_API_KEY"),
        getattr(settings, "GEMINI_API_KEY", None) if settings else None,
        getattr(settings, "GOOGLE_API_KEY", None) if settings else None,
    ]
    if any(k and isinstance(k, str) and k.strip() for k in env_keys):
        active_key, _, _ = gemini_key_pool.get_key()
        if active_key:
            return active_key
        for k in env_keys:
            if k and isinstance(k, str) and k.strip():
                return k.strip()
    return None


async def call_gemini(
    messages: list[dict[str, Any]],
    system_prompt: str,
    tools: Optional[list[dict[str, Any]]] = None,
    preferred_model: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 25.0
) -> tuple[Optional[str], str, bool]:
    """
    Call Google Gemini API with system instruction, multi-turn dialogue,
    automatic web_search function calling, thought signature preservation,
    and automatic fallback across models.

    Returns:
        (answer_text, used_model, search_used)
    """
    all_gemini_keys = gemini_key_pool.get_all_keys()
    if not all_gemini_keys:
        single_fallback = get_gemini_api_key()
        if single_fallback:
            all_gemini_keys = [single_fallback]
        else:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

    base_model = (
        preferred_model
        or os.getenv("GEMINI_MODEL")
        or getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest")
        or "gemini-flash-lite-latest"
    ).strip()

    models_to_try = list(dict.fromkeys([
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        base_model,
        "gemini-3.1-flash-lite"
    ]))

    # Convert incoming OpenAI-style messages into Gemini contents
    contents: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)

        if role in ("user", "assistant", "model") and content:
            gemini_role = "user" if role == "user" else "model"
            text_str = str(content).strip()
            if len(text_str) > 4000:
                text_str = text_str[:4000] + "..."
            contents.append({
                "role": gemini_role,
                "parts": [{"text": text_str}]
            })

    if not contents:
        raise ValueError("No valid user or assistant messages provided to call_gemini.")

    use_tools = tools if tools is not None else GEMINI_SEARCH_TOOLS
    payload: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }
    if use_tools:
        payload["tools"] = use_tools

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        close_client = True

    search_used = False
    last_error: Optional[Exception] = None

    try:
        from app.services.web_search_service import web_search

        ready_keys = gemini_key_pool.get_ready_keys()
        if not ready_keys:
            if all_gemini_keys:
                raise RuntimeError("All Gemini keys are currently rate-limited (in 60s cooldown).")
            else:
                raise RuntimeError("GEMINI_API_KEY is not configured.")

        for active_key in ready_keys:
            key_succeeded = False

            for model_id in models_to_try:
                url = GEMINI_API_URL_TEMPLATE.format(model=model_id)
                current_payload = dict(payload)

                for turn in range(3):
                    try:
                        resp = await client.post(
                            url,
                            json=current_payload,
                            headers={"x-goog-api-key": active_key},
                        )
                    except Exception as exc:
                        logger.warning("[Gemini] Connection error: %s", exc)
                        last_error = exc
                        break

                    if resp.status_code in (429, 503, 500):
                        logger.warning("[Gemini] Key hit HTTP %d: %s. Smart-switching key...", resp.status_code, resp.text[:120])
                        gemini_key_pool.mark_rate_limited(active_key, cooldown_seconds=60.0)
                        last_error = RuntimeError(f"HTTP_{resp.status_code}_{resp.text[:80]}")
                        break

                    if resp.status_code == 404:
                        logger.warning("[Gemini] Model %s returned 404. Trying next model...", model_id)
                        last_error = RuntimeError(f"MODEL_NOT_FOUND_{model_id}")
                        break

                    if resp.status_code != 200:
                        logger.warning("[Gemini] API error HTTP %d: %s", resp.status_code, resp.text[:120])
                        last_error = RuntimeError(f"HTTP_{resp.status_code}_{resp.text[:80]}")
                        break

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        last_error = RuntimeError("NO_CANDIDATES")
                        break

                    cand = candidates[0]
                    content_obj = cand.get("content", {})
                    parts = content_obj.get("parts", [])
                    if not parts:
                        last_error = RuntimeError("EMPTY_PARTS")
                        break

                    fc = parts[0].get("functionCall") if isinstance(parts[0], dict) else None
                    if fc and fc.get("name") == "web_search":
                        search_used = True
                        search_query = fc.get("args", {}).get("query", "")
                        w_res = await web_search(search_query)

                        if w_res["results"]:
                            s_snippets = [f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}" for r in w_res["results"]]
                            s_content = f"Search Results for '{search_query}':\n\n" + "\n\n".join(s_snippets)
                        else:
                            s_content = f"Search produced no reliable results. Check official site {w_res['official_site']}."

                        current_payload["contents"].append({
                            "role": "model",
                            "parts": parts
                        })
                        current_payload["contents"].append({
                            "role": "user",
                            "parts": [{
                                "functionResponse": {
                                    "name": "web_search",
                                    "response": {
                                        "name": "web_search",
                                        "content": s_content
                                    }
                                }
                            }]
                        })
                        continue

                    text_part = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p).strip()
                    if text_part:
                        if search_used and 'w_res' in locals():
                            if w_res.get("results") and not any(r["url"] in text_part for r in w_res["results"]):
                                top_url = w_res["results"][0]["url"]
                                text_part += f"\n\nSource: {top_url}"
                            elif not w_res.get("results") and "can't confirm this live" not in text_part.lower():
                                text_part = f"I can't confirm this live, check {w_res['official_site']}."

                        gemini_key_pool.mark_success(active_key)
                        return text_part, model_id, search_used

        if last_error:
            raise last_error
        raise RuntimeError("All Gemini models exhausted without response.")

    finally:
        if close_client:
            await client.aclose()
