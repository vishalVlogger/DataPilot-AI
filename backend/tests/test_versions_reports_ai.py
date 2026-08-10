import pandas as pd
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.ai.base import AIProvider
from app.services.ai.factory import get_ai_provider
from app.services.ai.mock import MockAIProvider
from app.services.ai.structured import validate_plan_json
from app.services.analytics.profiler import profile_dataset


def upload(client) -> str:
    return client.post("/api/datasets/upload", files={"file": ("sales.csv", b"Region,Sales\n West ,10\nNorth,20\n", "text/csv")}).json()["id"]


def test_version_creation_list_and_restore(client) -> None:
    dataset_id = upload(client)
    applied = client.post(f"/api/datasets/{dataset_id}/clean/apply", json={"operations": [{"type": "trim_whitespace", "column": "Region"}], "confirmed": True})
    assert applied.json()["version"] == 1
    versions = client.get(f"/api/datasets/{dataset_id}/versions").json()
    assert versions["current_version"] == 1 and [item["version"] for item in versions["versions"]] == [0, 1]
    restored = client.post(f"/api/datasets/{dataset_id}/versions/0/restore")
    assert restored.status_code == 200 and restored.json()["version"] == 2
    versions = client.get(f"/api/datasets/{dataset_id}/versions").json()
    assert versions["current_version"] == 2 and versions["versions"][0]["operation"] == "upload"


def test_html_report_real_values_and_options(client) -> None:
    dataset_id = upload(client)
    response = client.post(f"/api/datasets/{dataset_id}/report", json={"title": "Sales Report", "include_profile": True, "include_insights": False, "include_quality": False, "include_charts": False, "include_version_history": True})
    assert response.status_code == 200 and "Sales Report" in response.text
    assert "30" in response.text and "Version history" in response.text
    invalid = client.post(f"/api/datasets/{dataset_id}/report", json={"title": ""})
    assert invalid.status_code == 422


def test_provider_factory_and_invalid_structured_output() -> None:
    assert isinstance(get_ai_provider(Settings(ai_provider="mock")), MockAIProvider)
    with pytest.raises(AppError) as missing:
        get_ai_provider(Settings(ai_provider="openai", openai_api_key=None))
    assert missing.value.error_code == "AI_PROVIDER_UNAVAILABLE"
    with pytest.raises(AppError) as invalid:
        validate_plan_json('{"operation":"made_up"}')
    assert invalid.value.error_code == "AI_PLAN_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("question,operation", [
    ("Show West region sales above 50000 for the last 6 months grouped by product", "group_and_aggregate"),
    ("Compare Q1 and Q2 revenue by region", "trend"),
    ("Show top 5 customers in each region", "rank"),
    ("Which products declined for 3 consecutive months?", "pipeline"),
    ("Which products grew for 3 consecutive months?", "pipeline"),
    ("Show each region's contribution to total sales", "contribution"),
    ("Rank products by revenue within each region", "rank"),
    ("Show a 3-month moving average of revenue", "moving_average"),
    ("What percentage of total sales comes from the top 10 customers?", "contribution"),
    ("Which category has the highest variance in monthly sales?", "variance"),
])
async def test_advanced_mock_intents(question: str, operation: str) -> None:
    frame = pd.DataFrame({"Region": ["West", "North"], "Product": ["A", "B"], "Customer": ["C1", "C2"], "Category": ["X", "Y"], "Sales": [60000, 20000], "Revenue": [60000, 20000], "Date": ["2026-07-01", "2026-08-01"]})
    plan = await MockAIProvider().create_analysis_plan(question, profile_dataset(frame, "id")["columns"])
    assert plan.operation == operation


@pytest.mark.asyncio
async def test_mock_multi_metric_change_intent() -> None:
    frame = pd.DataFrame({"Customer": ["A", "A"], "Sales": [100, 120], "Average Order Value": [50, 40], "Date": ["2026-01-01", "2026-02-01"]})
    plan = await MockAIProvider().create_analysis_plan("Find customers whose sales increased but average order value decreased", profile_dataset(frame, "id")["columns"])
    assert plan.operation == "compare_segments" and plan.secondary_metric == "Average Order Value"


class FailingProvider(AIProvider):
    async def create_analysis_plan(self, question, columns):
        raise AppError("offline", "AI_PROVIDER_UNAVAILABLE", 503)
    async def explain_result(self, question, plan, result):
        raise AppError("offline", "AI_PROVIDER_UNAVAILABLE", 503)


def test_provider_failure_falls_back_to_deterministic_result(client, monkeypatch) -> None:
    import app.api.routes.datasets as routes
    dataset_id = upload(client)
    monkeypatch.setattr(routes, "get_ai_provider", lambda settings: FailingProvider())
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    from app.core.config import get_settings
    get_settings.cache_clear()
    response = client.post(f"/api/datasets/{dataset_id}/ask", json={"question": "What is the total sales?"})
    assert response.status_code == 200 and response.json()["result"]["value"] == 30
    assert response.json()["metadata"]["provider_fallback"] is True
