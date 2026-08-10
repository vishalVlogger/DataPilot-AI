import re
from typing import Any

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.ai.base import AIProvider


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _find_column(question: str, names: list[str], numeric_only: set[str] | None = None) -> str | None:
    normalized_question = f" {_normalized(question)} "
    candidates = [name for name in names if numeric_only is None or name in numeric_only]
    matches = [name for name in candidates if f" {_normalized(name)} " in normalized_question]
    return max(matches, key=len) if matches else None


class MockAIProvider(AIProvider):
    async def create_analysis_plan(self, question: str, columns: list[dict[str, Any]]) -> AnalysisPlan:
        names = [item["name"] for item in columns]
        numeric = {item["name"] for item in columns if item["category"] == "numeric"}
        q = _normalized(question)
        if re.search(r"\b(how many rows|row count|count rows|number of rows)\b", q):
            return AnalysisPlan(operation="count", aggregation="count")
        limit_match = re.search(r"\b(?:top|bottom)\s+(\d+)\b", q)
        if "top" in q or "bottom" in q:
            metric = _find_column(question, names, numeric)
            group = _find_column(question, names)
            if group == metric:
                group = None
            if not metric:
                metric = next(iter(numeric), None)
            non_numeric = [name for name in names if name not in numeric and name.lower() in q]
            group = max(non_numeric, key=len) if non_numeric else group
            if not group:
                raise AppError("Please name the category to group by, such as product or region.", "AMBIGUOUS_QUESTION")
            return AnalysisPlan(operation="top_n" if "top" in q else "bottom_n", metric=metric, group_by=group, aggregation="sum", limit=int(limit_match.group(1)) if limit_match else 10)
        operations = [("average", "mean"), ("mean", "mean"), ("minimum", "min"), ("lowest", "min"), ("maximum", "max"), ("highest", "max"), ("total", "sum"), ("sum", "sum")]
        aggregation = next((value for keyword, value in operations if keyword in q), None)
        if aggregation:
            metric = _find_column(question, names, numeric)
            if not metric:
                raise AppError("Please include the numeric column you want to analyze.", "AMBIGUOUS_QUESTION")
            return AnalysisPlan(operation="aggregate", metric=metric, aggregation=aggregation)
        if re.search(r"\b(count|how many)\b", q):
            return AnalysisPlan(operation="count", aggregation="count")
        raise AppError("This milestone supports total, average, min, max, count, top N, and bottom N questions.", "UNSUPPORTED_QUESTION")

    async def explain_result(self, question: str, plan: AnalysisPlan, result: Any) -> str:
        if plan.operation == "count":
            return f"The dataset contains {result['count']:,} rows."
        if plan.operation == "aggregate":
            labels = {"sum": "total", "mean": "average", "min": "minimum", "max": "maximum", "count": "count"}
            value = result["value"]
            rendered = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}" if isinstance(value, int) else str(value)
            return f"The {labels.get(plan.aggregation, plan.aggregation)} {plan.metric} is {rendered}."
        direction = "top" if plan.operation == "top_n" else "bottom"
        return f"Here are the {direction} {len(result)} {plan.group_by} values ranked by total {plan.metric}."
