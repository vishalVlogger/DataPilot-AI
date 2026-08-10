from typing import Any

import pandas as pd

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan


def execute_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> Any:
    if plan.operation == "count":
        return {"count": int(len(frame))}
    if not plan.metric or plan.metric not in frame.columns:
        raise AppError("A valid metric column is required.", "INVALID_PLAN")
    if plan.operation == "aggregate":
        series = pd.to_numeric(frame[plan.metric], errors="coerce").dropna()
        if series.empty:
            raise AppError(f"Column '{plan.metric}' has no numeric values.", "NON_NUMERIC_METRIC")
        functions = {"sum": series.sum, "mean": series.mean, "min": series.min, "max": series.max, "count": series.count}
        value = functions[plan.aggregation or "sum"]()
        return {"metric": plan.metric, "aggregation": plan.aggregation, "value": value.item() if hasattr(value, "item") else value}
    if not plan.group_by or plan.group_by not in frame.columns:
        raise AppError("A valid grouping column is required.", "INVALID_PLAN")
    working = frame[[plan.group_by, plan.metric]].copy()
    working[plan.metric] = pd.to_numeric(working[plan.metric], errors="coerce")
    working = working.dropna()
    if working.empty:
        raise AppError("No valid rows are available for this analysis.", "NO_ANALYSIS_DATA")
    grouped = working.groupby(plan.group_by, dropna=False)[plan.metric].sum().sort_values(ascending=plan.operation == "bottom_n").head(plan.limit)
    return [{plan.group_by: str(key), plan.metric: float(value)} for key, value in grouped.items()]
