from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from app.core.config import get_settings
from app.core.errors import AppError


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque); self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if not get_settings().rate_limit_enabled: return
        now = monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window_seconds: events.popleft()
            if len(events) >= limit: raise AppError("Too many requests. Please try again later.", "RATE_LIMITED", 429)
            events.append(now)

    def clear(self) -> None:
        with self._lock: self._events.clear()


rate_limiter = InMemoryRateLimiter()
