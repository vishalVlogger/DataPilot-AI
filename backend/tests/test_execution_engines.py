import pandas as pd
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, FilterCondition
from app.services.analytics.engines.duckdb_engine import DuckDBExecutionEngine
from app.services.analytics.engines.pandas_engine import PandasExecutionEngine
from app.services.analytics.engines.selector import ExecutionEngineSelector


@pytest.mark.asyncio
async def test_pandas_duckdb_grouped_parity() -> None:
    frame = pd.DataFrame({"Region": ["West", "North", "West"], "Sales": [20, 10, 30]})
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"], sort="desc")
    pandas_result = await PandasExecutionEngine().execute_plan(frame, plan)
    duck_result = await DuckDBExecutionEngine().execute_plan(frame, plan)
    assert pandas_result.result == duck_result.result
    assert pandas_result.engine == "pandas" and duck_result.engine == "duckdb"


@pytest.mark.asyncio
async def test_duckdb_trend_and_period_comparison() -> None:
    frame = pd.DataFrame({"Date": ["2026-01-01", "2026-02-01"], "Sales": [100, 150]})
    trend = await DuckDBExecutionEngine().execute_plan(frame, AnalysisPlan(operation="trend", metric="Sales", aggregation="sum", date_column="Date", time_granularity="month"))
    assert [row["Sales"] for row in trend.result] == [100, 150]
    comparison = await DuckDBExecutionEngine().execute_plan(frame, AnalysisPlan(operation="compare_periods", metric="Sales", aggregation="sum", date_column="Date", period_mode="month"))
    assert comparison.result["change"] == 50 and comparison.result["change_percentage"] == 50


@pytest.mark.asyncio
async def test_duckdb_multiple_filters_and_distinct() -> None:
    frame = pd.DataFrame({"Region": ["West", "North", "West"], "Sales": [20, 10, 30], "Customer": ["A", "B", "C"]})
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"], filters=[FilterCondition(column="Region", operator="in", value=["West", "North"]), FilterCondition(column="Sales", operator="greater_than", value=15)])
    result = await DuckDBExecutionEngine().execute_plan(frame, plan)
    assert result.result == [{"Region": "West", "Sales": 50.0}]


def test_engine_selection_and_resource_limit() -> None:
    settings = Settings(pandas_row_threshold=2, duckdb_row_threshold=2, max_analysis_rows=10)
    selector = ExecutionEngineSelector(settings)
    assert selector.select(1).name == "pandas"
    assert selector.select(2).name == "duckdb"
    with pytest.raises(AppError) as error:
        selector.select(11)
    assert error.value.error_code == "RESOURCE_LIMIT_EXCEEDED"
