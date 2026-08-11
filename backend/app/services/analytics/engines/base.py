from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pathlib import Path

import pandas as pd

from app.schemas.dataset import AnalysisPlan


@dataclass
class EngineResult:
    result: Any
    engine: str
    duration_ms: float


class AnalyticsExecutionEngine(ABC):
    name: str

    @abstractmethod
    async def execute_plan(self, dataset: pd.DataFrame | Path, plan: AnalysisPlan) -> EngineResult:
        raise NotImplementedError
