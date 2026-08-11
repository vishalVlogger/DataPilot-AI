from time import perf_counter

import pandas as pd
from pathlib import Path

from app.schemas.dataset import AnalysisPlan
from app.services.analytics.engines.base import AnalyticsExecutionEngine, EngineResult
from app.services.analytics.executor import execute_plan


class PandasExecutionEngine(AnalyticsExecutionEngine):
    name = "pandas"

    async def execute_plan(self, dataset: pd.DataFrame | Path, plan: AnalysisPlan) -> EngineResult:
        started = perf_counter()
        frame = pd.read_parquet(dataset) if isinstance(dataset, Path) else dataset
        result = execute_plan(frame, plan)
        return EngineResult(result=result, engine=self.name, duration_ms=round((perf_counter() - started) * 1000, 3))
