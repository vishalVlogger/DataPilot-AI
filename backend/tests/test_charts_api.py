import pandas as pd
import pytest

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.visualization.charts import generate_chart


def chart_frame() -> pd.DataFrame:
    return pd.DataFrame({"Region": ["West", "North"], "Sales": [200, 100], "Profit": [40, 10], "Date": ["2026-01-01", "2026-02-01"]})


@pytest.mark.parametrize("chart_type", ["bar", "column", "pie"])
def test_grouped_chart_data(chart_type: str) -> None:
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"])
    chart = generate_chart(chart_frame(), plan, chart_type)
    assert chart["type"] == chart_type and chart["data"][0]["Sales"] in {100, 200}


def test_line_and_scatter_chart_data() -> None:
    line = generate_chart(chart_frame(), AnalysisPlan(operation="trend", metric="Sales", aggregation="sum", date_column="Date", time_granularity="month"), "line")
    assert len(line["data"]) == 2
    scatter = generate_chart(chart_frame(), AnalysisPlan(operation="filter", metric="Profit", group_by=["Sales"]), "scatter")
    assert scatter["x_axis"] == "Sales" and scatter["y_axis"] == "Profit"


def test_invalid_chart_request() -> None:
    with pytest.raises(AppError):
        generate_chart(chart_frame(), AnalysisPlan(operation="aggregate", metric="Sales", aggregation="sum"), "bar")


def test_insights_quality_and_chart_endpoints(client) -> None:
    content = b"Region,Sales,Date\nWest,200,2026-01-01\nNorth,100,2026-02-01\n"
    dataset_id = client.post("/api/datasets/upload", files={"file": ("sales.csv", content, "text/csv")}).json()["id"]
    assert client.get(f"/api/datasets/{dataset_id}/insights").status_code == 200
    assert client.get(f"/api/datasets/{dataset_id}/quality").status_code == 200
    chart = client.post(f"/api/datasets/{dataset_id}/chart", json={"question": "Show sales by region", "chart_type": "bar"})
    assert chart.status_code == 200
    assert chart.json()["data"]
