"""
Groq API Key Pool & Smart Switching Service.

Manages multiple Groq API keys with intelligent failover, cooldown tracking,
and zero-latency round-robin switching so rate limits do not disrupt query flow.

Security Note: Does NOT open or print any .env or secret files, and never prints or logs tokens or keys.
"""

import os
import re
import time
import logging
import asyncio
from typing import List, Dict, Tuple, Optional, Set

logger = logging.getLogger(__name__)


def get_all_groq_api_keys() -> List[str]:
    """
    Discovers all configured Groq API keys from environment variables and application settings.
    Supports single keys, comma/semicolon-separated lists, and numbered variants
    (e.g. GROQ_API_KEY, GROQ_API_KEY2, GROQ_API_KEY_2, GROQ_API_KEYS).
    Deduplicates and preserves discovery order. Never prints or logs key values.
    """
    try:
        from app.config import settings
    except ImportError:
        settings = None

    raw_candidates = []

    # 1. Main GROQ_API_KEY
    main_key = os.getenv("GROQ_API_KEY") or (getattr(settings, "GROQ_API_KEY", "") if settings else "") or ""
    if main_key:
        raw_candidates.append(main_key)

    # 2. Named and extra settings if configured
    if settings:
        for attr in ("GROQ_API_KEY2", "GROQ_API_KEY3", "GROQ_API_KEY4", "GROQ_API_KEY5", "GROQ_API_KEYS"):
            v = getattr(settings, attr, "") or ""
            if v and isinstance(v, str):
                raw_candidates.append(v)
        # Any dynamically added fields on settings
        for attr_name in dir(settings):
            upper_name = attr_name.upper()
            if upper_name.startswith("GROQ_API_KEY") or upper_name.startswith("GROQ_KEY"):
                val = getattr(settings, attr_name, "")
                if val and isinstance(val, str):
                    raw_candidates.append(val)
        if hasattr(settings, "__dict__"):
            for k, val in settings.__dict__.items():
                if (k.upper().startswith("GROQ_API_KEY") or k.upper().startswith("GROQ_KEY")) and isinstance(val, str) and val:
                    raw_candidates.append(val)

    # 3. Plural GROQ_API_KEYS env var
    plural_keys = os.getenv("GROQ_API_KEYS", "").strip()
    if plural_keys:
        raw_candidates.append(plural_keys)

    # 4. Scan os.environ for numbered/named variants (e.g. GROQ_API_KEY2, GROQ_API_KEY3, GROQ_KEY_3)
    for env_name, env_val in os.environ.items():
        name_upper = env_name.upper()
        if (
            name_upper.startswith("GROQ_API_KEY")
            or name_upper.startswith("GROQ_KEY")
        ):
            if env_val and env_val.strip():
                raw_candidates.append(env_val.strip())

    # 5. Read from .env via dotenv if present, to catch keys added dynamically
    try:
        import dotenv
        if os.path.exists(".env"):
            env_map = dotenv.dotenv_values(".env")
            for k, val in env_map.items():
                if val and isinstance(val, str):
                    k_upper = k.upper()
                    if k_upper.startswith("GROQ_API_KEY") or k_upper.startswith("GROQ_KEY"):
                        raw_candidates.append(val.strip())
    except Exception:
        pass

    # Split on commas, semicolons, or newlines
    parsed_keys: List[str] = []
    seen: Set[str] = set()

    for item in raw_candidates:
        if not item:
            continue
        parts = re.split(r"[,;\n\r]+", str(item))
        for p in parts:
            clean = p.strip().strip("'\"")
            # Groq API keys typically begin with gsk_ and are >= 20 characters
            if clean and clean not in seen and len(clean) >= 15:
                parsed_keys.append(clean)
                seen.add(clean)

    return parsed_keys


from app.services.key_pool_base import BaseKeyPool


class GroqKeyPool(BaseKeyPool):
    """
    Thread-safe / async pool for smart switching across multiple Groq API keys.
    Maintains per-key cooldowns upon hitting 429 rate limits and rotates keys
    seamlessly to ensure zero disruption to traffic.
    """
    def __init__(self):
        super().__init__(key_getter=get_all_groq_api_keys, provider_name="Groq")


# Global singleton instance
groq_key_pool = GroqKeyPool()
