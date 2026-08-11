import json
from typing import Any

from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan


def plan_prompt(question: str, columns: list[dict[str, Any]]) -> str:
    schema = [{"name": item["name"], "physical_type": item.get("physical_type", item["category"]), "category": item["category"], "semantic_role": item.get("semantic_role", "unknown"), "temporal_helper": item.get("temporal_helper"), "allowed_aggregations": item.get("allowed_aggregations", [])} for item in columns]
    return f"Create one safe, semantically meaningful DataPilot analysis plan as JSON only. Never return SQL or Python. Respect semantic roles and allowed aggregations; temporal helpers are for grouping, chronological sorting, filtering, count, distinct_count, min, or max and must never be summed or averaged. Never sum temporal dimensions or identifiers. Ranking plans must explicitly identify their dimension, metric, aggregation, direction, and safe limit. Use max for 'most expensive', row count for 'most common', average for explicit average-price requests, and a sales/revenue/units measure for 'best-selling'. Dataset schema: {json.dumps(schema)}. Question: {question}"


def validate_plan_json(content: str) -> AnalysisPlan:
    try:
        payload = json.loads(content)
        return AnalysisPlan.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AppError("The AI provider returned an invalid structured analysis plan.", "AI_PLAN_INVALID", 502) from exc


def explanation_prompt(question: str, plan: AnalysisPlan, result: Any) -> str:
    return f"Explain this deterministic result concisely. Do not calculate or invent values. Question: {question}\nPlan: {plan.model_dump_json()}\nCalculated result: {json.dumps(result, default=str)}"
