import pandas as pd
import pytest

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, ReportRequest
from app.services.ai.mock import MockAIProvider
from app.services.ai.structured import plan_prompt
from app.services.analytics.executor import execute_plan, validate_plan
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.quality import analyze_quality
from app.services.analytics.semantics import ROLE_AGGREGATIONS
from app.services.reports.html import generate_html_report
from app.services.visualization.charts import generate_chart


@pytest.fixture()
def cars() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["Maruti Alto LXI", "Maruti Alto LXi", "Swift VDI", "City VX", "i20 Sportz", "Nexon XZ", "Creta SX", "Baleno Zeta", "Polo Highline", "Tiago XT"],
        "year": [2014, 2014, 2018, 2017, 2016, 2019, 2020, 2018, 2015, 2019],
        "selling_price": [220000, 225000, 620000, 850000, 510000, 900000, 1500000, 650000, 480000, 5000000],
        "km_driven": [70000, 68000, 45000, 35000, 50000, 30000, 18000, 42000, 60000, 25000],
        "fuel": ["Diesel", "Diesel", "Diesel", "Petrol", "Petrol", "Diesel", "Diesel", "Petrol", "CNG", "Electric"],
        "seller_type": ["Individual", "Individual", "Dealer", "Dealer", "Individual", "Dealer", "Dealer", "Individual", "Individual", "Dealer"],
        "transmission": ["Manual", "Manual", "Manual", "Automatic", "Manual", "Manual", "Automatic", "Manual", "Manual", "Automatic"],
        "owner": ["First Owner", "Second Owner", "First Owner", "First Owner", "Second Owner", "First Owner", "First Owner", "Second Owner", "Third Owner", "First Owner"],
    })


def roles(frame: pd.DataFrame) -> dict[str, dict]:
    return {item["name"]: item for item in profile_dataset(frame, "cars")["columns"]}


def test_car_details_semantic_roles(cars: pd.DataFrame) -> None:
    columns = roles(cars)
    assert columns["year"]["semantic_role"] == "temporal_dimension"
    assert columns["selling_price"]["semantic_role"] == "measure"
    assert columns["km_driven"]["semantic_role"] == "measure"
    assert columns["fuel"]["semantic_role"] == "categorical_dimension"
    assert columns["name"]["semantic_role"] == "high_cardinality_dimension"
    assert "sum" not in columns["year"]["allowed_aggregations"]
    assert "sum" in columns["selling_price"]["allowed_aggregations"]


def test_car_details_insights_are_semantically_meaningful(cars: pd.DataFrame) -> None:
    insights = generate_insights(cars, "cars")
    rendered = " ".join(f"{item['title']} {item['description']}" for item in insights).casefold()
    assert "total year" not in rendered
    assert "diesel is the most common fuel" in rendered
    assert "based on row counts" in rendered
    assert "selling price" in rendered and "average" in rendered
    assert not any(item["type"] == "outlier" and item.get("metric") == "year" for item in insights)
    assert any(item["type"] == "outlier" and item.get("metric") == "selling_price" for item in insights)


def test_high_cardinality_variants_are_review_oriented(cars: pd.DataFrame) -> None:
    issue = next(item for item in analyze_quality(cars) if item["column"] == "name" and item["issue_type"] == "possible_category_variant")
    assert issue["confidence"] == "low" and issue["severity"] == "info"
    assert "review recommended" in issue["message"].lower()


def test_general_semantic_detection_and_policy() -> None:
    frame = pd.DataFrame({
        "model_year": [2019, 2020, 2021, 2022, 2023],
        "customer_id": [101, 102, 103, 104, 105],
        "revenue": [10, 20, 30, 40, 50],
        "price": [2.5, 3.0, 3.5, 4.0, 4.5],
        "active": [True, False, True, False, True],
        "description": ["a", "b", "c", "d", "e"],
    })
    columns = roles(frame)
    assert columns["model_year"]["semantic_role"] == "temporal_dimension"
    assert columns["customer_id"]["semantic_role"] == "identifier"
    assert columns["revenue"]["semantic_role"] == "measure"
    assert columns["price"]["semantic_role"] == "measure"
    assert columns["active"]["semantic_role"] == "boolean_dimension"
    assert columns["description"]["semantic_role"] == "high_cardinality_dimension"
    assert ROLE_AGGREGATIONS["identifier"] == ["count", "distinct_count"]

    with pytest.raises(AppError) as year_error:
        validate_plan(frame, AnalysisPlan(operation="aggregate", metric="model_year", aggregation="sum"))
    assert year_error.value.error_code == "SEMANTIC_AGGREGATION_INVALID"
    with pytest.raises(AppError):
        validate_plan(frame, AnalysisPlan(operation="aggregate", metric="model_year"))
    with pytest.raises(AppError):
        validate_plan(frame, AnalysisPlan(operation="aggregate", metric="customer_id", aggregation="mean"))
    assert execute_plan(frame, AnalysisPlan(operation="aggregate", metric="revenue", aggregation="sum"))["value"] == 150
    assert execute_plan(frame, AnalysisPlan(operation="aggregate", metric="price", aggregation="mean"))["value"] == 3.5


@pytest.mark.asyncio
async def test_mock_provider_uses_semantic_roles(cars: pd.DataFrame) -> None:
    columns = profile_dataset(cars, "cars")["columns"]; provider = MockAIProvider()
    common = await provider.create_analysis_plan("Which fuel type is most common?", columns)
    assert common.operation == "group_and_aggregate" and common.group_by == ["fuel"] and common.aggregation == "count" and common.metric == "fuel"
    average = await provider.create_analysis_plan("Which fuel type has highest average selling price?", columns)
    assert average.metric == "selling_price" and average.group_by == ["fuel"] and average.aggregation == "mean"
    yearly = await provider.create_analysis_plan("Show selling price trend by year", columns)
    assert yearly.operation == "group_and_aggregate" and yearly.group_by == ["year"] and yearly.aggregation == "mean" and yearly.sort == "asc"


def test_semantic_chart_rules_provider_context_and_report(cars: pd.DataFrame) -> None:
    columns = profile_dataset(cars, "cars")["columns"]
    prompt = plan_prompt("total selling price", columns)
    assert '"semantic_role": "temporal_dimension"' in prompt and "never sum temporal" in prompt.lower()
    yearly = AnalysisPlan(operation="group_and_aggregate", metric="selling_price", aggregation="mean", group_by=["year"], sort="asc")
    chart = generate_chart(cars, yearly)
    assert chart["type"] == "line"
    with pytest.raises(AppError) as pie:
        generate_chart(cars, AnalysisPlan(operation="group_and_aggregate", metric="selling_price", aggregation="mean", group_by=["name"]), "pie")
    assert pie.value.error_code == "CHART_NOT_SUPPORTED"
    html, _ = generate_html_report(cars, "cars", ReportRequest(title="Car report"), {"current_version": 0, "versions": []})
    assert "Semantic column profile" in html and "temporal dimension" in html
    assert "total year" not in html.casefold()


def test_quality_findings_include_confidence(cars: pd.DataFrame) -> None:
    issues = analyze_quality(cars)
    assert issues and all(item["confidence"] in {"low", "medium", "high"} and item.get("message") for item in issues)
