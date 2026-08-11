from abc import ABC, abstractmethod
from collections.abc import Callable
from threading import Thread

from app.core.config import get_settings
from app.core.errors import AppError


class JobExecutor(ABC):
    @abstractmethod
    def submit(self, target: Callable, *args) -> None: ...


class LocalJobExecutor(JobExecutor):
    def submit(self, target: Callable, *args) -> None:
        Thread(target=target, args=args, daemon=True).start()


def get_job_executor() -> JobExecutor:
    mode = get_settings().job_execution_mode.casefold()
    if mode == "local": return LocalJobExecutor()
    raise AppError("Configured distributed job execution is not available in this process.", "JOB_EXECUTOR_UNAVAILABLE", 503)
