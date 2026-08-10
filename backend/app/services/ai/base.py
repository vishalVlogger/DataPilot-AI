from abc import ABC, abstractmethod
from typing import Any

from app.schemas.dataset import AnalysisPlan


class AIProvider(ABC):
    @abstractmethod
    async def create_analysis_plan(self, question: str, columns: list[dict[str, Any]]) -> AnalysisPlan:
        raise NotImplementedError

    @abstractmethod
    async def explain_result(self, question: str, plan: AnalysisPlan, result: Any) -> str:
        raise NotImplementedError
