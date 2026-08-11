from abc import ABC, abstractmethod
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from app.core.config import get_settings
from app.core.errors import AppError


class RateLimiter(ABC):
    @abstractmethod
    def check(self, key: str, limit: int, window_seconds: int = 60) -> None: ...
    @abstractmethod
    def clear(self) -> None: ...


class InMemoryRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

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


class RedisRateLimiter(RateLimiter):
    def __init__(self, url: str) -> None:
        try:
            from redis import Redis
            self.client = Redis.from_url(url, decode_responses=True)
        except Exception as exc:
            raise AppError("Redis rate limiting is unavailable.", "RATE_LIMIT_BACKEND_UNAVAILABLE", 503) from exc

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if not get_settings().rate_limit_enabled: return
        redis_key = f"datapilot:rate:{key}"
        try:
            with self.client.pipeline() as pipe:
                pipe.incr(redis_key); pipe.expire(redis_key, window_seconds, nx=True)
                count, _ = pipe.execute()
        except Exception as exc:
            raise AppError("Rate limiting is temporarily unavailable.", "RATE_LIMIT_BACKEND_UNAVAILABLE", 503) from exc
        if int(count) > limit: raise AppError("Too many requests. Please try again later.", "RATE_LIMITED", 429)

    def clear(self) -> None:
        return None


class ConfiguredRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self.memory = InMemoryRateLimiter()
        self._redis: RedisRateLimiter | None = None
        self._redis_url: str | None = None

    def _backend(self) -> RateLimiter:
        settings = get_settings()
        if settings.rate_limit_backend.casefold() != "redis": return self.memory
        if not settings.redis_url: raise AppError("REDIS_URL is required for Redis rate limiting.", "RATE_LIMIT_BACKEND_INVALID", 503)
        if self._redis is None or self._redis_url != settings.redis_url:
            self._redis = RedisRateLimiter(settings.redis_url); self._redis_url = settings.redis_url
        return self._redis

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None: self._backend().check(key, limit, window_seconds)
    def clear(self) -> None:
        self.memory.clear()


rate_limiter = ConfiguredRateLimiter()
