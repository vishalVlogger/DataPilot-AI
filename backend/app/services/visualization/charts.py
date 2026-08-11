from typing import Any

import pandas as pd

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.analytics.executor import execute_plan, validate_plan
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.semantics import describe_chart_plan, recommend_chart_type, sort_temporal_records, temporal_axis_kind

HIGH_CARDINALITY_CHART_LIMIT = 25


def generate_chart(frame: pd.DataFrame, plan: AnalysisPlan, chart_type: str | None = None, max_rows: int = 100, title: str | None = None, x_axis_label: str | None = None, y_axis_label: str | None = None, show_legend: bool = True, question: str | None = None) -> dict[str, Any]:
    validate_plan(frame, plan)
    profile = profile_dataset(frame, "chart")
    by_name = {item["name"]: item for item in profile["columns"]}
    recommended_type = recommend_chart_type(profile["columns"], plan)
    selected_type = chart_type or recommended_type
    if selected_type not in {"bar", "column", "line", "pie", "scatter"}:
        raise AppError("The requested chart type is not supported.", "CHART_NOT_SUPPORTED")
    if selected_type == "pie" and plan.group_by and by_name.get(plan.group_by[0], {}).get("semantic_role") in {"identifier", "high_cardinality_dimension"}:
        raise AppError("Pie charts are not suitable for identifier or high-cardinality dimensions.", "CHART_NOT_SUPPORTED")
    group_role = by_name.get(plan.group_by[0], {}).get("semantic_role") if plan.group_by else None
    safe_limit = min(max_rows, HIGH_CARDINALITY_CHART_LIMIT) if group_role == "high_cardinality_dimension" else max_rows
    if selected_type == "scatter":
        if not plan.metric or not plan.group_by:
            raise AppError("Scatter charts require two numeric columns.", "INVALID_QUERY_PLAN")
        x_axis, y_axis = plan.group_by[0], plan.metric
        if not pd.api.types.is_numeric_dtype(frame[x_axis]) or not pd.api.types.is_numeric_dtype(frame[y_axis]):
            raise AppError("Scatter chart axes must be numeric.", "INVALID_AGGREGATION")
        data = frame[[x_axis, y_axis]].dropna().head(max_rows).to_dict(orient="records")
    else:
        temporal_axis = (
            plan.operation == "group_and_aggregate"
            and bool(plan.group_by)
            and temporal_axis_kind(plan.group_by[0], profile["columns"])
        )
        chart_plan = plan.model_copy(update={"limit": safe_limit}) if plan.limit > safe_limit else plan
        if temporal_axis and chart_plan.limit < max_rows:
            chart_plan = chart_plan.model_copy(update={"limit": max_rows})
        result = execute_plan(frame, chart_plan)
        if not isinstance(result, list):
            raise AppError("This query does not produce chartable rows.", "CHART_NOT_SUPPORTED")
        data = result[:safe_limit]
        x_axis = "Period" if plan.operation == "trend" else plan.group_by[0]
        y_axis = "count" if plan.aggregation == "count" else plan.metric or "Value"
        if plan.operation != "trend": data = sort_temporal_records(data, x_axis, frame, profile["columns"])
    interpretation = describe_chart_plan(chart_plan if selected_type != "scatter" else plan, question, len(data) if group_role == "high_cardinality_dimension" and plan.limit > safe_limit else None)
    chart_title = title or interpretation["interpreted_as"]
    drill_down = {"filter_template": {"column": x_axis, "operator": "equals", "value": "{clicked_value}"}, "suggested_grouping": "Choose another categorical column"} if selected_type != "scatter" else None
    return {"type": selected_type, "title": chart_title, "x_axis": x_axis, "y_axis": y_axis, "x_axis_label": x_axis_label or interpretation["x_axis_label"], "y_axis_label": y_axis_label or interpretation["y_axis_label"], "tooltip_label": interpretation["tooltip_label"], "data": data, "plan": chart_plan if selected_type != "scatter" else plan, "interpreted_request": interpretation["interpreted_as"], "interpretation": interpretation, "recommended_chart_type": recommended_type, "selected_chart_type": selected_type, "show_legend": show_legend, "drill_down": drill_down}
