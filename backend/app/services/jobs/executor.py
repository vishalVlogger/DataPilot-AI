from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from threading import Thread, Timer

from app.core.config import get_settings
from app.core.errors import AppError


class JobExecutor(ABC):
    @abstractmethod
    def submit(self, job_id: str, target: Callable, *args) -> None: ...
    @abstractmethod
    def retry_later(self, job_id: str, delay_seconds: int, target: Callable, *args) -> None: ...


class LocalJobExecutor(JobExecutor):
    def submit(self, job_id: str, target: Callable, *args) -> None:
        Thread(target=target, args=args, daemon=True, name=f"datapilot-job-{job_id[:8]}").start()
    def retry_later(self, job_id: str, delay_seconds: int, target: Callable, *args) -> None:
        timer = Timer(delay_seconds, lambda: self.submit(job_id, target, *args)); timer.daemon = True; timer.start()


class RedisJobExecutor(JobExecutor):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.redis_url: raise AppError("REDIS_URL is required for Redis job execution.", "JOB_EXECUTOR_UNAVAILABLE", 503)
        from redis import Redis
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True); self.queue = settings.job_queue_name
    def submit(self, job_id: str, target: Callable, *args) -> None:
        self.redis.rpush(self.queue, job_id)
    def retry_later(self, job_id: str, delay_seconds: int, target: Callable, *args) -> None:
        import time
        self.redis.zadd(f"{self.queue}:delayed", {job_id: time.time() + delay_seconds})


def get_job_executor() -> JobExecutor:
    mode = get_settings().job_execution_mode.casefold()
    if mode == "local": return LocalJobExecutor()
    if mode == "redis": return RedisJobExecutor()
    raise AppError("Configured job execution mode is invalid.", "JOB_EXECUTOR_UNAVAILABLE", 503)


def queue_diagnostics() -> dict:
    settings = get_settings()
    if settings.job_execution_mode.casefold() != "redis": return {"mode": "local", "worker_connected": True, "queue_depth": 0, "retrying_jobs": 0}
    if not settings.redis_url: return {"mode": "redis", "worker_connected": False, "queue_depth": None, "retrying_jobs": None}
    try:
        import time
        from redis import Redis
        redis = Redis.from_url(settings.redis_url, decode_responses=True); queue = settings.job_queue_name
        heartbeat = redis.get(f"{queue}:worker:heartbeat")
        oldest = redis.lindex(queue, 0)
        return {"mode": "redis", "worker_connected": bool(heartbeat), "queue_depth": redis.llen(queue), "oldest_queued_job": oldest, "retrying_jobs": redis.zcard(f"{queue}:delayed"), "checked_at": time.time()}
    except Exception: return {"mode": "redis", "worker_connected": False, "queue_depth": None, "retrying_jobs": None, "status": "unavailable"}
