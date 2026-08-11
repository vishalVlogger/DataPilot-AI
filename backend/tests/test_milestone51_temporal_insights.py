from io import BytesIO

import pandas as pd
import pytest
from pypdf import PdfReader

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, ReportRequest
from app.services.ai.mock import MockAIProvider
from app.services.ai.structured import plan_prompt
from app.services.analytics.executor import execute_plan, validate_plan
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.reports import generate_html_report, generate_pdf_report
from app.services.visualization.charts import generate_chart


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


@pytest.fixture()
def financial_sample() -> pd.DataFrame:
    month_numbers = list(range(1, 13)) * 3
    month_names = MONTHS * 3
    segments = ["Government"] * 15 + ["Small Business"] * 9 + ["Enterprise"] * 6 + ["Midmarket"] * 6
    return pd.DataFrame({
        "Segment": segments,
        "Country": ["Canada", "France", "Germany"] * 12,
        "Product": ["Paseo", "VTT", "Amarilla", "Carretera"] * 9,
        "Discount Band": ["None", "Low", "Medium"] * 12,
        "Units Sold": [100 + index for index in range(36)],
        "Manufacturing Price": [10 + index % 4 for index in range(36)],
        "Sale Price": [20 + index % 5 for index in range(36)],
        "Gross Sales": [1000 + index * 20 for index in range(36)],
        "Discounts": [index % 4 for index in range(36)],
        "Sales": [1200 - index * 7 for index in range(36)],
        "COGS": [600 + index * 3 for index in range(36)],
        "Profit": [300 + index * 5 for index in range(36)],
        "Date": pd.to_datetime([f"2024-{month:02d}-01" for month in month_numbers]),
        "Month Number": month_numbers,
        "Month Name": month_names,
        "Year": [2024] * 36,
    })


def columns(frame: pd.DataFrame) -> dict[str, dict]:
    return {item["name"]: item for item in profile_dataset(frame, "fixture")["columns"]}


@pytest.mark.parametrize("name,values,kind", [
    ("month-number", [1, 2, 12, 6], "month"),
    ("Month No", [1, 4, 8, 12], "month"),
    ("fiscal_month", [1, 3, 6, 12], "month"),
    ("Quarter Number", [1, 2, 3, 4], "quarter"),
    ("fiscal-quarter", [1, 2, 3, 4], "quarter"),
    ("Week Number", [1, 12, 52, 53], "week"),
    ("day_of_week", [1, 2, 6, 7], "day"),
])
def test_temporal_helper_names_and_ranges(name: str, values: list[int], kind: str) -> None:
    item = columns(pd.DataFrame({name: values}))[name]
    assert item["semantic_role"] == "temporal_dimension"
    assert item["temporal_helper"] == kind
    assert set(item["allowed_aggregations"]) == {"count", "distinct_count", "min", "max"}
    assert not {"sum", "average", "median"} & set(item["allowed_aggregations"])


def test_invalid_ranges_and_false_positive_are_not_temporal_helpers() -> None:
    frame = pd.DataFrame({"Month Number": [100, 200, 300, 400], "Quarter": [1, 2, 99, 100], "Month Sales": [100, 200, 300, 400], "Quarter Revenue": [20, 30, 40, 50]})
    found = columns(frame)
    assert found["Month Number"].get("temporal_helper") is None
    assert found["Quarter"].get("temporal_helper") is None
    assert found["Month Sales"]["semantic_role"] == "measure"
    assert found["Quarter Revenue"]["semantic_role"] == "measure"


def test_financial_sample_semantics_validation_and_provider_context(financial_sample: pd.DataFrame) -> None:
    found = columns(financial_sample)
    assert found["Month Number"]["semantic_role"] == "temporal_dimension" and found["Month Number"]["temporal_helper"] == "month"
    assert "sum" not in found["Month Number"]["allowed_aggregations"]
    assert found["Year"]["semantic_role"] == "temporal_dimension"
    assert found["Sales"]["semantic_role"] == "measure" and found["Profit"]["semantic_role"] == "measure"
    assert found["Month Name"]["semantic_role"] in {"categorical_dimension", "temporal_dimension"}
    with pytest.raises(AppError) as invalid:
        validate_plan(financial_sample, AnalysisPlan(operation="aggregate", metric="Month Number", aggregation="sum"))
    assert invalid.value.error_code == "SEMANTIC_AGGREGATION_INVALID"
    prompt = plan_prompt("Show sales by month", list(found.values()))
    assert '"temporal_helper": "month"' in prompt and "must never be summed or averaged" in prompt


@pytest.mark.asyncio
async def test_mock_prefers_date_then_ordered_month_helper(financial_sample: pd.DataFrame) -> None:
    provider = MockAIProvider()
    profile = profile_dataset(financial_sample, "financial")["columns"]
    with_date = await provider.create_analysis_plan("Show sales by month", profile)
    assert with_date.operation == "trend" and with_date.date_column == "Date" and with_date.metric == "Sales"
    periods = execute_plan(financial_sample, with_date)
    assert [row["Period"] for row in periods] == sorted(row["Period"] for row in periods)

    without_date = financial_sample.drop(columns="Date")
    helper_plan = await provider.create_analysis_plan("Show sales by month", profile_dataset(without_date, "financial")["columns"])
    assert helper_plan.operation == "group_and_aggregate"
    assert helper_plan.group_by == ["Month Name", "Month Number"]
    assert helper_plan.metric == "Sales" and helper_plan.aggregation == "sum"
    rows = execute_plan(without_date, helper_plan)
    assert [row["Month Name"] for row in rows] == MONTHS


def test_temporal_chart_ordering_for_month_quarter_and_week() -> None:
    monthly = pd.DataFrame({"Month Number": list(range(1, 13)), "Month Name": MONTHS, "Sales": list(range(12))})
    month_chart = generate_chart(monthly, AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Month Name"]), "column")
    assert month_chart["x_axis"] == "Month Name"
    assert [row["Month Name"] for row in month_chart["data"]] == MONTHS

    quarterly = pd.DataFrame({"Quarter": [4, 1, 3, 2], "Sales": [40, 10, 30, 20]})
    quarter_chart = generate_chart(quarterly, AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Quarter"]), "column")
    assert [row["Quarter"] for row in quarter_chart["data"]] == [1, 2, 3, 4]

    weekly = pd.DataFrame({"Week Number": [10, 2, 1, 3], "Sales": [10, 2, 1, 3]})
    week_chart = generate_chart(weekly, AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Week Number"]), "line")
    assert [row["Week Number"] for row in week_chart["data"]] == [1, 2, 3, 10]


def test_distribution_deduplication_and_report_wording(financial_sample: pd.DataFrame) -> None:
    insights = generate_insights(financial_sample, "financial")
    government = [item for item in insights if "government" in item["title"].casefold() and "segment" in item["title"].casefold()]
    assert len([item for item in government if "most common" in item["title"].casefold()]) == 1
    assert not any("represents" in item["title"].casefold() for item in government)
    common = next(item for item in government if "most common" in item["title"].casefold())
    assert "15 records" in common["description"] and "41.7%" in common["description"]

    versions = {"current_version": 1, "versions": [{"version": 1, "created_at": "2026-01-01T00:00:00", "operation": "clean", "description": "Trimmed values", "affected_rows": 4}]}
    options = ReportRequest(title="Financial Sample", include_profile=True, include_insights=True, include_quality=False, include_charts=False, include_version_history=True)
    html, _ = generate_html_report(financial_sample, "financial", options, versions)
    folded = html.casefold()
    assert "affected rows" in folded and "sum(month number)" not in folded
    assert folded.count("government is the most common segment") == 1
    assert "government represents 41.7% of segment values" not in folded

    pdf = generate_pdf_report(financial_sample, "financial", options, versions)
    text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "Affected Rows" in text and "SUM(Month Number)" not in text
    assert text.casefold().count("government is the most common segment") == 1
