"""
Unified Key Pool Base Service.
Handles thread-safe round-robin selection, 60s rate limit cooldown windows,
earliest-expiry wait calculations, and graceful pause/unpause for multi-key providers.

Security Note: Does NOT log or print keys or tokens.
"""
import time
import logging
from typing import List, Dict, Tuple, Optional, Set, Callable

logger = logging.getLogger(__name__)


class BaseKeyPool:
    def __init__(self, key_getter: Callable[[], List[str]], provider_name: str = "API"):
        self._key_getter = key_getter
        self.provider_name = provider_name
        self._cooldowns: Dict[str, float] = {}
        self._current_index: int = 0
        self._paused_until: float = 0.0

    def pause(self, minutes: float = 30.0):
        self._paused_until = time.time() + (minutes * 60.0)
        logger.warning(
            "[%s Key Pool] Key pool paused for %.1f minutes (until %s).",
            self.provider_name, minutes, time.strftime("%H:%M:%S", time.localtime(self._paused_until))
        )

    def unpause(self):
        self._paused_until = 0.0

    def is_paused(self) -> bool:
        return time.time() < self._paused_until

    def get_all_keys(self) -> List[str]:
        if self.is_paused():
            return []
        return self._key_getter()

    def get_key_count(self) -> int:
        return len(self.get_all_keys())

    def get_key(self, exclude_keys: Optional[Set[str]] = None) -> Tuple[Optional[str], int, float]:
        if self.is_paused():
            return None, -1, max(0.0, self._paused_until - time.time())

        keys = self.get_all_keys()
        if not keys:
            return None, -1, 0.0

        exclude = exclude_keys or set()
        now = time.time()
        num_keys = len(keys)

        for offset in range(num_keys):
            idx = (self._current_index + offset) % num_keys
            candidate = keys[idx]
            if candidate in exclude:
                continue

            cooldown_expiry = self._cooldowns.get(candidate, 0.0)
            if now >= cooldown_expiry:
                self._current_index = (idx + 1) % num_keys
                return candidate, idx, 0.0

        best_candidate = None
        best_idx = 0
        earliest_expiry = float("inf")

        for idx, candidate in enumerate(keys):
            if candidate in exclude:
                continue
            expiry = self._cooldowns.get(candidate, 0.0)
            if expiry < earliest_expiry:
                earliest_expiry = expiry
                best_candidate = candidate
                best_idx = idx

        if best_candidate is not None:
            remaining_wait = max(0.0, earliest_expiry - now)
            return best_candidate, best_idx, remaining_wait

        return None, -1, 0.0

    def get_ready_keys(self, exclude_keys: Optional[Set[str]] = None) -> List[str]:
        """Returns all configured keys that are currently ready (not in cooldown)."""
        if self.is_paused():
            return []
        keys = self.get_all_keys()
        if not keys:
            return []
        exclude = exclude_keys or set()
        now = time.time()
        return [k for k in keys if k not in exclude and now >= self._cooldowns.get(k, 0.0)]

    def has_ready_key(self, exclude_keys: Optional[Set[str]] = None) -> bool:
        """Returns True if at least one key is ready right now (not in cooldown)."""
        return len(self.get_ready_keys(exclude_keys=exclude_keys)) > 0

    def all_keys_cooling(self) -> bool:
        """
        Returns True when every configured key for this provider is currently in a cooldown window.
        Returns False if there are no keys configured, or if at least one key is ready.
        """
        keys = self.get_all_keys()
        if not keys:
            return False
        now = time.time()
        return all(now < self._cooldowns.get(k, 0.0) for k in keys)

    def mark_rate_limited(self, key: str, cooldown_seconds: float = 60.0):
        keys = self._key_getter()
        key_idx = keys.index(key) if key in keys else -1
        self._cooldowns[key] = time.time() + cooldown_seconds
        display_idx = f"#{key_idx + 1}" if key_idx >= 0 else "(unregistered)"
        logger.warning(
            "[%s Smart Switch] Key %s hit rate limit (429/503). Cooldown set for %.1fs. Smart-switching to next available key...",
            self.provider_name, display_idx, cooldown_seconds
        )

    def mark_success(self, key: str):
        if key in self._cooldowns:
            self._cooldowns.pop(key, None)

    def clear_cooldowns(self):
        """Clears all active cooldowns, making all configured keys available again."""
        self._cooldowns.clear()

