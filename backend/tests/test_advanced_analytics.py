from datetime import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, DateFilter, FilterCondition, PipelineStep, SortRule
from app.services.analytics.executor import execute_plan, validate_plan
from app.utils.dates import relative_date_range


def advanced_frame() -> pd.DataFrame:
    rows = []
    values = {"A": [100, 90, 80, 70], "B": [10, 20, 30, 40]}
    for product, sales in values.items():
        for month, value in enumerate(sales, 1):
            rows.append({"Region": "West" if product == "A" else "North", "Product": product, "Sales": value, "Profit": value / 10, "Date": f"2026-{month:02d}-01"})
    return pd.DataFrame(rows)


def test_multiple_group_filter_and_sort_rules() -> None:
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region", "Product"], filters=[FilterCondition(column="Sales", operator="greater_than", value=15), FilterCondition(column="Region", operator="not_in", value=["Other"])], sort=[SortRule(column="Region", direction="asc"), SortRule(column="Sales", direction="desc")], limit=20)
    result = execute_plan(advanced_frame(), plan)
    assert result[0]["Region"] == "North" and {"Region", "Product", "Sales"}.issubset(result[0])


def test_relative_date_boundaries() -> None:
    start, end = relative_date_range("last_3_months", datetime(2026, 8, 10))
    assert str(start.date()) == "2026-06-01" and str(end.date()) == "2026-08-11"
    start, end = relative_date_range("previous_year", datetime(2026, 8, 10))
    assert start.year == 2025 and end.year == 2026


def test_contribution_rank_and_correlation() -> None:
    frame = advanced_frame()
    contribution = execute_plan(frame, AnalysisPlan(operation="contribution", metric="Sales", aggregation="sum", group_by=["Product"], sort="desc"))
    assert round(sum(row["percentage_of_total"] for row in contribution), 2) == 100
    rank = execute_plan(frame, AnalysisPlan(operation="rank", metric="Sales", aggregation="sum", group_by=["Region", "Product"], partition_by=["Region"], limit=5))
    assert all(row["rank"] == 1 for row in rank)
    correlation = execute_plan(frame, AnalysisPlan(operation="correlation", metric="Sales", secondary_metric="Profit"))
    assert correlation["correlation"] == pytest.approx(1)
    percent = execute_plan(frame, AnalysisPlan(operation="percent_of_total", metric="Sales", aggregation="sum", group_by=["Product"]))
    assert round(sum(row["percentage_of_total"] for row in percent), 2) == 100


def test_moving_average_percentage_change_and_consecutive() -> None:
    frame = advanced_frame()
    moving = execute_plan(frame, AnalysisPlan(operation="moving_average", metric="Sales", date_column="Date", time_granularity="month", window=3, limit=20))
    assert moving[2]["moving_average"] == 110
    change = execute_plan(frame, AnalysisPlan(operation="percentage_change", metric="Sales", date_column="Date", time_granularity="month", limit=20))
    assert change[1]["percentage_change"] is not None
    decline = execute_plan(frame, AnalysisPlan(operation="consecutive_decline", metric="Sales", group_by=["Product"], date_column="Date", time_granularity="month", periods=3))
    growth = execute_plan(frame, AnalysisPlan(operation="consecutive_growth", metric="Sales", group_by=["Product"], date_column="Date", time_granularity="month", periods=3))
    assert decline[0]["Product"] == "A" and growth[0]["Product"] == "B"


def test_pipeline_and_invalid_pipeline() -> None:
    frame = advanced_frame()
    plan = AnalysisPlan(operation="pipeline", metric="Sales", group_by=["Product"], date_column="Date", steps=[PipelineStep(operation="trend", metric="Sales", group_by=["Product"], date_column="Date", time_granularity="month"), PipelineStep(operation="consecutive_decline", periods=3)])
    assert execute_plan(frame, plan)[0]["Product"] == "A"
    with pytest.raises(AppError):
        validate_plan(frame, AnalysisPlan(operation="pipeline", steps=[PipelineStep(operation="rank")]))
    with pytest.raises(ValidationError):
        PipelineStep(operation="execute_python")


def test_multi_metric_segment_change_and_monthly_variance() -> None:
    frame = pd.DataFrame({"Customer": ["A", "A", "B", "B"], "Sales": [100, 150, 100, 80], "Average Order Value": [50, 40, 20, 25], "Date": ["2026-01-01", "2026-02-01", "2026-01-01", "2026-02-01"]})
    plan = AnalysisPlan(operation="compare_segments", metric="Sales", secondary_metric="Average Order Value", aggregation="sum", secondary_aggregation="mean", group_by=["Customer"], date_column="Date", period_mode="month")
    result = execute_plan(frame, plan)
    assert result[0]["Customer"] == "A" and result[0]["Sales_change"] == 50
    variance_frame = advanced_frame()
    variance = execute_plan(variance_frame, AnalysisPlan(operation="variance", metric="Sales", group_by=["Product"], date_column="Date", time_granularity="month", sort="desc"))
    assert variance[0]["Sales"] > 0
