from app.core.config import Settings
from app.core.errors import AppError
from app.services.analytics.engines.base import AnalyticsExecutionEngine
from app.services.analytics.engines.duckdb_engine import DuckDBExecutionEngine
from app.services.analytics.engines.pandas_engine import PandasExecutionEngine


class ExecutionEngineSelector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select(self, row_count: int) -> AnalyticsExecutionEngine:
        if row_count > self.settings.max_analysis_rows:
            raise AppError(f"Dataset exceeds the {self.settings.max_analysis_rows:,} analysis row limit.", "RESOURCE_LIMIT_EXCEEDED", 413)
        forced = self.settings.forced_execution_engine
        if forced:
            if forced == "pandas": return PandasExecutionEngine()
            if forced == "duckdb": return DuckDBExecutionEngine()
            raise AppError("Invalid forced execution engine.", "EXECUTION_ENGINE_FAILED", 500)
        return DuckDBExecutionEngine() if row_count >= self.settings.duckdb_row_threshold else PandasExecutionEngine()
