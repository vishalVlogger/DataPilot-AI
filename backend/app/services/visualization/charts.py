from typing import Any

import pandas as pd

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.analytics.executor import execute_plan, validate_plan


def generate_chart(frame: pd.DataFrame, plan: AnalysisPlan, chart_type: str | None = None, max_rows: int = 100) -> dict[str, Any]:
    validate_plan(frame, plan)
    selected_type = chart_type or ("line" if plan.operation == "trend" else "bar")
    if selected_type not in {"bar", "column", "line", "pie", "scatter"}:
        raise AppError("The requested chart type is not supported.", "CHART_NOT_SUPPORTED")
    if selected_type == "scatter":
        if not plan.metric or not plan.group_by:
            raise AppError("Scatter charts require two numeric columns.", "INVALID_QUERY_PLAN")
        x_axis, y_axis = plan.group_by[0], plan.metric
        if not pd.api.types.is_numeric_dtype(frame[x_axis]) or not pd.api.types.is_numeric_dtype(frame[y_axis]):
            raise AppError("Scatter chart axes must be numeric.", "INVALID_AGGREGATION")
        data = frame[[x_axis, y_axis]].dropna().head(max_rows).to_dict(orient="records")
    else:
        result = execute_plan(frame, plan)
        if not isinstance(result, list):
            raise AppError("This query does not produce chartable rows.", "CHART_NOT_SUPPORTED")
        data = result[:max_rows]
        x_axis = "Period" if plan.operation == "trend" else plan.group_by[0]
        y_axis = plan.metric or "Value"
    title = f"{y_axis} by {x_axis}"
    return {"type": selected_type, "title": title, "x_axis": x_axis, "y_axis": y_axis, "data": data, "plan": plan, "interpreted_request": title}
