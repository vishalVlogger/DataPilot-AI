from time import perf_counter

import pandas as pd

from app.schemas.dataset import AnalysisPlan
from app.services.analytics.engines.base import AnalyticsExecutionEngine, EngineResult
from app.services.analytics.executor import execute_plan


class PandasExecutionEngine(AnalyticsExecutionEngine):
    name = "pandas"

    async def execute_plan(self, dataset: pd.DataFrame, plan: AnalysisPlan) -> EngineResult:
        started = perf_counter()
        result = execute_plan(dataset, plan)
        return EngineResult(result=result, engine=self.name, duration_ms=round((perf_counter() - started) * 1000, 3))
