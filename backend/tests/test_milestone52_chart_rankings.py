import pandas as pd
import pytest

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.ai.mock import MockAIProvider
from app.services.analytics.engines.duckdb_engine import DuckDBExecutionEngine
from app.services.analytics.executor import execute_plan
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.semantics import recommend_chart_type
from app.services.visualization.charts import HIGH_CARDINALITY_CHART_LIMIT, generate_chart


@pytest.fixture()
def cars() -> pd.DataFrame:
    names = [f"Car {index:02d}" for index in range(30)] + ["Car 00", "Car 00", "Car 01"]
    return pd.DataFrame({
        "name": names,
        "year": [2020 + index % 5 for index in range(len(names))],
        "selling_price": [100_000 + index * 25_000 for index in range(len(names))],
        "km_driven": [80_000 - index * 1_000 for index in range(len(names))],
        "fuel": ["Petrol" if index % 2 else "Diesel" for index in range(len(names))],
    })


@pytest.mark.asyncio
async def test_ambiguous_car_ranking_uses_transparent_price_default(cars: pd.DataFrame) -> None:
    columns = profile_dataset(cars, "cars")["columns"]
    assert next(item for item in columns if item["name"] == "name")["semantic_role"] == "high_cardinality_dimension"
    plan = await MockAIProvider().create_analysis_plan("Show me the top 5 car names", columns)
    chart = generate_chart(cars, plan, question="Show me the top 5 car names")
    assert (plan.operation, plan.metric, plan.aggregation, plan.group_by, plan.sort, plan.limit) == ("top_n", "selling_price", "mean", ["name"], "desc", 5)
    assert chart["type"] == chart["recommended_chart_type"] == "bar"
    assert chart["interpretation"]["inferred"] is True
    assert chart["interpretation"]["interpreted_as"] == "Top 5 car names by average selling price"
    assert chart["x_axis_label"] == "Car name" and chart["y_axis_label"] == "Average selling price"
    assert chart["title"] == chart["interpretation"]["interpreted_as"]
    assert len(chart["data"]) == 5
    assert [row["selling_price"] for row in chart["data"]] == sorted((row["selling_price"] for row in chart["data"]), reverse=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "operation", "aggregation"),
    [
        ("Show top 5 car names by average selling price", "top_n", "mean"),
        ("Show the top 5 most expensive cars", "top_n", "max"),
        ("Show bottom 5 cars by price", "bottom_n", "mean"),
    ],
)
async def test_price_ranking_intents(cars: pd.DataFrame, question: str, operation: str, aggregation: str) -> None:
    plan = await MockAIProvider().create_analysis_plan(question, profile_dataset(cars, "cars")["columns"])
    assert plan.operation == operation and plan.metric == "selling_price" and plan.aggregation == aggregation and plan.limit == 5
    assert plan.sort == ("asc" if operation == "bottom_n" else "desc")


@pytest.mark.asyncio
async def test_most_common_uses_row_count_in_pandas_and_duckdb(cars: pd.DataFrame) -> None:
    plan = await MockAIProvider().create_analysis_plan("Show top 5 most common cars", profile_dataset(cars, "cars")["columns"])
    assert plan.metric == "name" and plan.aggregation == "count" and plan.limit == 5
    pandas_rows = execute_plan(cars, plan)
    duckdb_rows = (await DuckDBExecutionEngine().execute_plan(cars, plan)).result
    assert pandas_rows == duckdb_rows
    assert pandas_rows[0] == {"name": "Car 00", "count": 3}
    chart = generate_chart(cars, plan)
    assert chart["y_axis"] == "count" and chart["tooltip_label"] == "Row count" and chart["type"] == "bar"


@pytest.mark.asyncio
async def test_generic_best_selling_and_profitable_ranking_rules() -> None:
    frame = pd.DataFrame({
        "Product": ["A", "B", "C", "A", "B", "C"],
        "Segment": ["Retail", "Retail", "Retail", "Enterprise", "Enterprise", "Enterprise"],
        "Sales": [10, 20, 30, 40, 50, 60],
        "Profit": [2, 3, 4, 10, 12, 14],
    })
    columns = profile_dataset(frame, "sales")["columns"]
    provider = MockAIProvider()
    selling = await provider.create_analysis_plan("Show top 10 best-selling products", columns)
    profitable = await provider.create_analysis_plan("Show the most profitable segments", columns)
    assert (selling.group_by, selling.metric, selling.aggregation, selling.limit) == (["Product"], "Sales", "sum", 10)
    assert (profitable.group_by, profitable.metric, profitable.aggregation, profitable.limit) == (["Segment"], "Profit", "sum", 10)


def test_semantic_recommendations_and_manual_override(cars: pd.DataFrame) -> None:
    columns = profile_dataset(cars, "cars")["columns"]
    temporal = AnalysisPlan(operation="group_and_aggregate", metric="selling_price", aggregation="mean", group_by=["year"])
    categorical = AnalysisPlan(operation="group_and_aggregate", metric="selling_price", aggregation="mean", group_by=["fuel"])
    high_rank = AnalysisPlan(operation="top_n", metric="selling_price", aggregation="mean", group_by=["name"], limit=5)
    scatter = AnalysisPlan(operation="filter", metric="selling_price", group_by=["km_driven"])
    distribution = AnalysisPlan(operation="group_and_aggregate", metric="fuel", aggregation="count", group_by=["fuel"])
    assert recommend_chart_type(columns, temporal) == "line"
    assert recommend_chart_type(columns, categorical) == "bar"
    assert recommend_chart_type(columns, high_rank) == "bar"
    assert recommend_chart_type(columns, scatter) == "scatter"
    assert recommend_chart_type(columns, distribution) == "bar"
    override = generate_chart(cars, high_rank, "line")
    assert override["selected_chart_type"] == "line" and override["recommended_chart_type"] == "bar"


def test_high_cardinality_chart_is_safely_limited(cars: pd.DataFrame) -> None:
    plan = AnalysisPlan(operation="group_and_aggregate", metric="selling_price", aggregation="mean", group_by=["name"], sort="desc", limit=100)
    chart = generate_chart(cars, plan)
    assert len(chart["data"]) == HIGH_CARDINALITY_CHART_LIMIT
    assert chart["plan"].limit == HIGH_CARDINALITY_CHART_LIMIT
    assert chart["interpretation"]["limit"] == HIGH_CARDINALITY_CHART_LIMIT


@pytest.mark.asyncio
async def test_unknown_explicit_ranking_metric_is_rejected(cars: pd.DataFrame) -> None:
    with pytest.raises(AppError) as error:
        await MockAIProvider().create_analysis_plan("Show top 5 cars by horsepower", profile_dataset(cars, "cars")["columns"])
    assert error.value.error_code == "COLUMN_NOT_FOUND"
