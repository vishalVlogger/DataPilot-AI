import pandas as pd
import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, FilterCondition
from app.services.analytics.executor import execute_plan, validate_plan
from app.services.analytics.profiler import profile_dataset
from app.services.ai.mock import MockAIProvider


@pytest.fixture()
def sales() -> pd.DataFrame:
    return pd.DataFrame({
        "Region": ["North", "West", "North", "West"],
        "Customer": ["A", "B", "A", "C"],
        "Sales": [100, 200, 50, 300],
        "Order Date": ["2026-01-01", "2026-01-20", "2026-02-01", "2026-02-20"],
    })


def test_valid_plan_group_and_aggregate(sales: pd.DataFrame) -> None:
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"], sort="desc")
    result = execute_plan(sales, plan)
    assert result == [{"Region": "West", "Sales": 500}, {"Region": "North", "Sales": 150}]


def test_invalid_column_and_aggregation(sales: pd.DataFrame) -> None:
    with pytest.raises(AppError, match="not found"):
        validate_plan(sales, AnalysisPlan(operation="aggregate", metric="Missing", aggregation="sum"))
    with pytest.raises(ValidationError):
        AnalysisPlan(operation="aggregate", metric="Sales", aggregation="variance")


def test_invalid_filter_shape() -> None:
    with pytest.raises(ValidationError):
        FilterCondition(column="Sales", operator="between", value=[10])


def test_filtering_and_distinct_count(sales: pd.DataFrame) -> None:
    filtered = execute_plan(sales, AnalysisPlan(operation="filter", filters=[FilterCondition(column="Sales", operator="greater_than", value=150)], limit=10))
    assert len(filtered) == 2
    distinct = execute_plan(sales, AnalysisPlan(operation="distinct_count", metric="Customer"))
    assert distinct["distinct_count"] == 3


def test_trend_and_period_comparison(sales: pd.DataFrame) -> None:
    trend = execute_plan(sales, AnalysisPlan(operation="trend", metric="Sales", aggregation="sum", date_column="Order Date", time_granularity="month", limit=100))
    assert [row["Sales"] for row in trend] == [300, 350]
    comparison = execute_plan(sales, AnalysisPlan(operation="compare_periods", metric="Sales", aggregation="sum", date_column="Order Date", period_mode="month"))
    assert comparison["change"] == 50 and comparison["change_percentage"] == pytest.approx(16.67)


def test_top_and_bottom_n(sales: pd.DataFrame) -> None:
    top = execute_plan(sales, AnalysisPlan(operation="top_n", metric="Sales", aggregation="sum", group_by=["Region"], limit=1))
    bottom = execute_plan(sales, AnalysisPlan(operation="bottom_n", metric="Sales", aggregation="sum", group_by=["Region"], limit=1))
    assert top[0]["Region"] == "West"
    assert bottom[0]["Region"] == "North"


@pytest.mark.asyncio
@pytest.mark.parametrize("question,operation", [
    ("Show sales by region", "group_and_aggregate"),
    ("Compare North and West sales", "compare_groups"),
    ("Show monthly sales trend", "trend"),
    ("Which month had the highest sales?", "trend"),
    ("Compare this month with the previous month sales", "compare_periods"),
    ("Count unique customers", "distinct_count"),
    ("Show sales for January", "aggregate"),
    ("Show customers where sales are above 100", "filter"),
])
async def test_supported_natural_language_examples(sales: pd.DataFrame, question: str, operation: str) -> None:
    columns = profile_dataset(sales, "id")["columns"]
    plan = await MockAIProvider().create_analysis_plan(question, columns)
    assert plan.operation == operation
    execute_plan(sales, plan)


@pytest.mark.asyncio
async def test_group_decline_and_scatter_plans() -> None:
    data = pd.DataFrame({"Product": ["A", "B", "A", "B"], "Sales": [100, 100, 50, 120], "Profit": [10, 20, 5, 25], "Date": ["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"]})
    columns = profile_dataset(data, "id")["columns"]
    provider = MockAIProvider()
    decline = await provider.create_analysis_plan("Which product declined the most?", columns)
    result = execute_plan(data, decline)
    assert decline.operation == "compare_periods" and result[0]["Product"] == "A"
    scatter = await provider.create_analysis_plan("Plot sales vs profit", columns)
    assert scatter.metric == "Profit" and scatter.group_by == ["Sales"]
