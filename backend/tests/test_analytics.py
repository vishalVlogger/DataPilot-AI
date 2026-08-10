import pandas as pd
import pytest

from app.schemas.dataset import AnalysisPlan
from app.services.ai.mock import MockAIProvider
from app.services.analytics.executor import execute_plan
from app.services.analytics.profiler import profile_dataset


def frame() -> pd.DataFrame:
    return pd.DataFrame({"Product": ["A", "B", "A", "A"], "Revenue": [10.0, 20.0, None, 30.0], "Order Date": ["2026-01-01", "2026-01-02", "bad", "2026-01-04"]})


def test_profile_statistics_missing_duplicates_and_types() -> None:
    data = frame()
    data.loc[3] = data.loc[0]
    profile = profile_dataset(data, "id")
    revenue = next(c for c in profile["columns"] if c["name"] == "Revenue")
    assert profile["missing_values"] == 1
    assert profile["duplicate_rows"] == 1
    assert revenue["sum"] == 40.0
    assert revenue["mean"] == pytest.approx(40 / 3)
    assert "Revenue" in profile["numeric_columns"]
    assert "Order Date" in profile["date_columns"]


def test_aggregate_top_and_bottom() -> None:
    data = frame()
    assert execute_plan(data, AnalysisPlan(operation="aggregate", metric="Revenue", aggregation="sum"))["value"] == 60
    top = execute_plan(data, AnalysisPlan(operation="top_n", metric="Revenue", group_by="Product", aggregation="sum", limit=1))
    bottom = execute_plan(data, AnalysisPlan(operation="bottom_n", metric="Revenue", group_by="Product", aggregation="sum", limit=1))
    assert top[0]["Product"] == "A" and top[0]["Revenue"] == 40
    assert bottom[0]["Product"] == "B" and bottom[0]["Revenue"] == 20


@pytest.mark.asyncio
async def test_mock_provider_plans() -> None:
    provider = MockAIProvider()
    columns = [{"name": "Product", "category": "categorical"}, {"name": "Revenue", "category": "numeric"}]
    plan = await provider.create_analysis_plan("Show top 5 products by revenue", columns)
    assert plan.operation == "top_n" and plan.limit == 5 and plan.metric == "Revenue"
    plan = await provider.create_analysis_plan("What is the average revenue?", columns)
    assert plan.aggregation == "mean"
