import pandas as pd

from app.services.analytics.insights import generate_insights
from app.services.analytics.quality import analyze_quality


def test_insights_include_performance_growth_decline_and_quality() -> None:
    frame = pd.DataFrame({
        "Region": ["West", "West", "North", "North", "West", "West", "West"],
        "Sales": [100, 100, 50, 50, 400, 20, 20],
        "Date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-02-01", "2026-03-01", "2026-03-01"],
        "Note": [None, None, "x", None, None, None, None],
    })
    insights = generate_insights(frame, "id")
    types = {item["type"] for item in insights}
    assert {"performance", "growth", "decline", "data_quality"}.issubset(types)
    assert any("West" in item["title"] and "most common" in item["title"] for item in insights)
    assert any("North" in item["title"] and "least common" in item["title"] for item in insights)
    assert any(item["title"] == "Duplicate rows detected" for item in insights)


def test_quality_detects_whitespace_case_duplicates_and_missing() -> None:
    frame = pd.DataFrame({"City": [" Mumbai", "MUMBAI", "mumbai", "mumbai"], "Value": [1, 2, None, None]})
    issues = analyze_quality(frame)
    kinds = {item["issue_type"] for item in issues}
    assert "leading_whitespace" in kinds
    assert "suspicious_category_variants" in kinds
    assert "missing_values" in kinds
    assert "duplicate_rows" in kinds
