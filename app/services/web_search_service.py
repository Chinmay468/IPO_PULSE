"""
Web Search Tool for Live & Time-Sensitive Financial Information.
Restricted to official regulatory sites (SEBI, NSE, BSE, RBI) and reputable Indian finance media.
Includes 1-hour in-memory TTL caching, rate limiting, request timeout, and untrusted data sanitization.
"""
import os
import re
import time
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Cache: query_key -> (results, timestamp)
_SEARCH_CACHE: Dict[str, Tuple[List[Dict[str, str]], float]] = {}
CACHE_TTL_SECONDS: float = 3600.0  # 1 hour

# Rate Limiting: list of request timestamps
_SEARCH_RATE_LIMIT: List[float] = []
RATE_LIMIT_WINDOW_SECONDS: float = 60.0
RATE_LIMIT_MAX_SEARCHES: int = 10

ALLOWED_DOMAINS = [
    "sebi.gov.in",
    "nseindia.com",
    "bseindia.com",
    "rbi.org.in",
    "moneycontrol.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "financialexpress.com",
    "business-standard.com",
    "reuters.com"
]

DEFAULT_OFFICIAL_SITE_BY_TOPIC = {
    "sebi": "sebi.gov.in",
    "nse": "nseindia.com",
    "bse": "bseindia.com",
    "rbi": "rbi.org.in",
    "repo rate": "rbi.org.in",
    "monetary policy": "rbi.org.in",
    "governor": "rbi.org.in",
    "chairperson": "sebi.gov.in",
    "settlement": "sebi.gov.in",
    "margin": "sebi.gov.in",
    "nifty": "nseindia.com",
    "sensex": "bseindia.com",
}


def sanitize_search_snippet(text: str) -> str:
    """
    Treats search result data as untrusted external content.
    Strips system prompt injection attempts, instructions, or control patterns.
    """
    if not text:
        return ""
    # Strip potential instruction overrides or system prompt leaks in snippet
    clean = re.sub(r'(?i)(?:ignore\s+previous|system\s+prompt|disregard|override|print\s+key|reveal\s+token)', '[filtered]', text)
    # Remove HTML tags if present
    clean = re.sub(r'<[^>]+>', ' ', clean)
    return clean.strip()


def get_official_site_suggestion(query: str) -> str:
    """Returns official domain recommendation based on query keywords."""
    q_lower = query.lower()
    for kw, domain in DEFAULT_OFFICIAL_SITE_BY_TOPIC.items():
        if kw in q_lower:
            return domain
    return "sebi.gov.in or nseindia.com"


def is_rate_limited() -> bool:
    """Enforces sliding window rate limit for search tool execution."""
    now = time.time()
    global _SEARCH_RATE_LIMIT
    _SEARCH_RATE_LIMIT = [t for t in _SEARCH_RATE_LIMIT if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(_SEARCH_RATE_LIMIT) >= RATE_LIMIT_MAX_SEARCHES:
        return True
    _SEARCH_RATE_LIMIT.append(now)
    return False


async def web_search(query: str) -> Dict[str, Any]:
    """
    Performs web search restricted to allowed financial domains.
    Returns structured results:
    {
        "query": str,
        "results": [{"title": str, "url": str, "snippet": str}],
        "source_used": bool,
        "official_site": str,
        "error": Optional[str]
    }
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return {
            "query": query,
            "results": [],
            "source_used": False,
            "official_site": "sebi.gov.in",
            "error": "Empty search query"
        }

    official_site = get_official_site_suggestion(clean_q)
    cache_key = clean_q.lower()

    # Check 1-hour cache
    now = time.time()
    if cache_key in _SEARCH_CACHE:
        cached_res, timestamp = _SEARCH_CACHE[cache_key]
        if now - timestamp < CACHE_TTL_SECONDS:
            logger.info("[WebSearch Cache Hit] query=%r results_count=%d", clean_q, len(cached_res))
            return {
                "query": clean_q,
                "results": cached_res,
                "source_used": len(cached_res) > 0,
                "official_site": official_site,
                "error": None
            }

    # Check Rate Limit
    if is_rate_limited():
        logger.warning("[WebSearch Rate Limited] query=%r", clean_q)
        return {
            "query": clean_q,
            "results": [],
            "source_used": False,
            "official_site": official_site,
            "error": f"Search rate limit exceeded ({RATE_LIMIT_MAX_SEARCHES} per minute)"
        }

    # Fetch Search API Key (Serper, Tavily, or SEARCH_API_KEY from environment)
    search_key = (
        os.getenv("SEARCH_API_KEY")
        or os.getenv("SERPER_API_KEY")
        or os.getenv("TAVILY_API_KEY")
        or getattr(settings, "SEARCH_API_KEY", None)
    )

    results: List[Dict[str, str]] = []
    error_msg: Optional[str] = None

    # Domain restriction filter string
    domain_filter = " OR ".join(f"site:{d}" for d in ALLOWED_DOMAINS)
    full_search_query = f"{clean_q} ({domain_filter})"

    try:
        if search_key and "serper" in (os.getenv("SERPER_API_KEY", "") or search_key).lower():
            # Serper API (https://google.serper.dev/search)
            url = "https://google.serper.dev/search"
            headers = {"X-API-KEY": search_key, "Content-Type": "application/json"}
            payload = {"q": full_search_query, "num": 3}
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    organic = data.get("organic", [])
                    for item in organic[:3]:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": sanitize_search_snippet(item.get("snippet", ""))
                        })
                else:
                    error_msg = f"Serper API HTTP {resp.status_code}"
        elif search_key and "tvly" in search_key.lower():
            # Tavily Search API
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json"}
            payload = {
                "api_key": search_key,
                "query": clean_q,
                "include_domains": ALLOWED_DOMAINS,
                "max_results": 3
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("results", [])[:3]:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "snippet": sanitize_search_snippet(item.get("content", ""))
                        })
                else:
                    error_msg = f"Tavily API HTTP {resp.status_code}"
        else:
            # Fallback DuckDuckGo HTML parser for domain-restricted search without external paid API key
            url = "https://html.duckduckgo.com/html/"
            params = {"q": full_search_query}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IPOPulseBot/1.0"}
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.post(url, data=params, headers=headers)
                if resp.status_code == 200:
                    html_text = resp.text
                    # Extract title, url, snippet from DDG html results
                    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html_text, re.DOTALL)
                    links = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.DOTALL)
                    titles = re.findall(r'<a class="result__a"[^>]*>(.*?)</a>', html_text, re.DOTALL)

                    for i in range(min(len(titles), 3)):
                        raw_title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                        raw_snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                        raw_url = links[i][0].strip() if i < len(links) else ""
                        if raw_url.startswith("//duckduckgo.com/l/?uddg="):
                            import urllib.parse
                            parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                            raw_url = parsed_qs.get("uddg", [raw_url])[0]

                        # Verify domain is allowed
                        if any(dom in raw_url for dom in ALLOWED_DOMAINS):
                            results.append({
                                "title": raw_title,
                                "url": raw_url,
                                "snippet": sanitize_search_snippet(raw_snippet)
                            })
                else:
                    error_msg = f"Fallback search HTTP {resp.status_code}"

    except Exception as exc:
        logger.warning("[WebSearch Exception] query=%r err=%s", clean_q, exc)
        error_msg = str(exc)

    # Store in 1-hour cache if results found
    if results:
        _SEARCH_CACHE[cache_key] = (results, now)

    logger.info(
        "[WebSearch Executed] query=%r results_found=%d official_site=%s error=%s",
        clean_q, len(results), official_site, error_msg
    )

    return {
        "query": clean_q,
        "results": results[:3],
        "source_used": len(results) > 0,
        "official_site": official_site,
        "error": error_msg
    }
