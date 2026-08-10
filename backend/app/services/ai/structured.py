import json
from typing import Any

from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan


def plan_prompt(question: str, columns: list[dict[str, Any]]) -> str:
    schema = [{"name": item["name"], "category": item["category"]} for item in columns]
    return f"Create one safe DataPilot analysis plan as JSON only. Never return SQL or Python. Dataset schema: {json.dumps(schema)}. Question: {question}"


def validate_plan_json(content: str) -> AnalysisPlan:
    try:
        payload = json.loads(content)
        return AnalysisPlan.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AppError("The AI provider returned an invalid structured analysis plan.", "AI_PLAN_INVALID", 502) from exc


def explanation_prompt(question: str, plan: AnalysisPlan, result: Any) -> str:
    return f"Explain this deterministic result concisely. Do not calculate or invent values. Question: {question}\nPlan: {plan.model_dump_json()}\nCalculated result: {json.dumps(result, default=str)}"
