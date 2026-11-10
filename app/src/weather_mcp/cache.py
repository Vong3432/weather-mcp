import time
from typing import Any


class TTLCache:
    """Minimal in-process cache. One Fargate task, so no shared store is needed."""

    def __init__(self, ttl_seconds: float, max_items: int = 5000):
        self._ttl = ttl_seconds
        self._max = max_items
        self._items: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if expires_at < time.monotonic():
            del self._items[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if len(self._items) >= self._max:
            self._items.clear()
        self._items[key] = (time.monotonic() + self._ttl, value)
