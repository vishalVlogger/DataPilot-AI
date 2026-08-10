from typing import Any

import pandas as pd
import calendar

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, FilterCondition

NUMERIC_AGGREGATIONS = {"sum", "mean", "min", "max", "median"}
DATE_OPERATIONS = {"trend", "compare_periods"}


def _value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def validate_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> None:
    columns = set(map(str, frame.columns))
    referenced = ([plan.metric] if plan.metric else []) + plan.group_by + ([plan.date_column] if plan.date_column else []) + [item.column for item in plan.filters]
    missing = [column for column in referenced if column not in columns]
    if missing:
        raise AppError(f"Column '{missing[0]}' was not found.", "COLUMN_NOT_FOUND")
    needs_metric = plan.operation not in {"count", "filter", "sort", "distinct_count"}
    if needs_metric and not plan.metric:
        raise AppError("This operation requires a metric column.", "INVALID_QUERY_PLAN")
    if plan.operation == "distinct_count" and not (plan.metric or plan.group_by):
        raise AppError("Distinct count requires a column.", "INVALID_QUERY_PLAN")
    if plan.aggregation in NUMERIC_AGGREGATIONS and plan.metric and not pd.api.types.is_numeric_dtype(frame[plan.metric]):
        converted = pd.to_numeric(frame[plan.metric], errors="coerce")
        if converted.notna().sum() == 0:
            raise AppError(f"Column '{plan.metric}' is not numeric.", "INVALID_AGGREGATION")
    if plan.operation in {"group_and_aggregate", "top_n", "bottom_n", "compare_groups"} and not plan.group_by:
        raise AppError("This operation requires a group-by column.", "INVALID_QUERY_PLAN")
    if plan.operation in DATE_OPERATIONS:
        if not plan.date_column:
            raise AppError("This operation requires a date column.", "INVALID_DATE_COLUMN")
        parsed = pd.to_datetime(frame[plan.date_column], errors="coerce")
        if parsed.notna().sum() == 0:
            raise AppError(f"Column '{plan.date_column}' is not date-compatible.", "INVALID_DATE_COLUMN")


def _filter(frame: pd.DataFrame, condition: FilterCondition) -> pd.Series:
    series = frame[condition.column]
    operator, value = condition.operator, condition.value
    try:
        if operator in {"before", "after"}:
            parsed = pd.to_datetime(series, errors="coerce")
            target = pd.to_datetime(value)
            return parsed < target if operator == "before" else parsed > target
        if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal", "between"}:
            numeric = pd.to_numeric(series, errors="coerce")
            if operator == "greater_than": return numeric > float(value)
            if operator == "greater_than_or_equal": return numeric >= float(value)
            if operator == "less_than": return numeric < float(value)
            if operator == "less_than_or_equal": return numeric <= float(value)
            return numeric.between(float(value[0]), float(value[1]), inclusive="both")
        text = series.astype("string")
        if operator == "equals": return text.str.casefold() == str(value).casefold()
        if operator == "not_equals": return text.str.casefold() != str(value).casefold()
        if operator == "contains":
            month_names = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
            if str(value).casefold() in month_names:
                parsed = pd.to_datetime(series, errors="coerce")
                if parsed.notna().any():
                    return parsed.dt.month == month_names[str(value).casefold()]
            return text.str.contains(str(value), case=False, regex=False, na=False)
        if operator == "starts_with": return text.str.startswith(str(value), na=False)
        if operator == "ends_with": return text.str.endswith(str(value), na=False)
        if operator == "in": return text.str.casefold().isin([str(item).casefold() for item in value])
    except (TypeError, ValueError) as exc:
        raise AppError(f"Invalid filter for column '{condition.column}'.", "INVALID_FILTER") from exc
    raise AppError("Unsupported filter operator.", "INVALID_FILTER")


def apply_filters(frame: pd.DataFrame, filters: list[FilterCondition]) -> pd.DataFrame:
    if not filters:
        return frame
    mask = pd.Series(True, index=frame.index)
    for condition in filters:
        mask &= _filter(frame, condition).fillna(False)
    return frame.loc[mask]


def _aggregate(series: pd.Series, aggregation: str) -> Any:
    if aggregation == "count":
        return int(series.count())
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        raise AppError("No numeric values are available for this analysis.", "INVALID_AGGREGATION")
    functions = {"sum": numeric.sum, "mean": numeric.mean, "min": numeric.min, "max": numeric.max, "median": numeric.median}
    return _value(functions[aggregation]())


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(key): _value(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]


def execute_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> Any:
    validate_plan(frame, plan)
    working = apply_filters(frame, plan.filters)
    if plan.operation == "count":
        return {"count": int(len(working))}
    if plan.operation == "distinct_count":
        column = plan.metric or plan.group_by[0]
        return {"column": column, "distinct_count": int(working[column].nunique(dropna=True))}
    if plan.operation == "filter":
        return _records(working.head(plan.limit))
    if plan.operation == "sort":
        column = plan.metric or plan.group_by[0]
        return _records(working.sort_values(column, ascending=plan.sort != "desc").head(plan.limit))
    if plan.operation == "aggregate":
        aggregation = plan.aggregation or "sum"
        return {"metric": plan.metric, "aggregation": aggregation, "value": _aggregate(working[plan.metric], aggregation)}
    if plan.operation == "trend":
        return trend(working, plan.metric, plan.date_column, plan.time_granularity or "month", plan.aggregation or "sum")
    if plan.operation == "compare_periods":
        if plan.group_by:
            return compare_periods_by_group(working, plan.metric, plan.date_column, plan.group_by[0], plan.period_mode or "month", plan.aggregation or "sum", plan.sort or "asc", plan.limit)
        return compare_periods(working, plan.metric, plan.date_column, plan.period_mode or "month", plan.aggregation or "sum")
    groups = plan.group_by
    aggregation = plan.aggregation or "sum"
    selected = working[groups + [plan.metric]].copy()
    selected[plan.metric] = pd.to_numeric(selected[plan.metric], errors="coerce")
    selected = selected.dropna(subset=[plan.metric])
    if plan.compare_values:
        selected = selected[selected[groups[0]].astype(str).str.casefold().isin([value.casefold() for value in plan.compare_values])]
    grouped = selected.groupby(groups, dropna=False)[plan.metric].agg(aggregation).reset_index()
    ascending = plan.operation == "bottom_n" or plan.sort == "asc"
    if plan.operation in {"top_n", "bottom_n"} or plan.sort:
        grouped = grouped.sort_values(plan.metric, ascending=ascending)
    return _records(grouped.head(plan.limit))


def trend(frame: pd.DataFrame, metric: str, date_column: str, granularity: str = "month", aggregation: str = "sum") -> list[dict[str, Any]]:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[metric], errors="coerce")
    working = pd.DataFrame({"date": dates, metric: values}).dropna()
    frequencies = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
    working["Period"] = working["date"].dt.to_period(frequencies[granularity]).astype(str)
    grouped = working.groupby("Period")[metric].agg(aggregation).reset_index().sort_values("Period")
    grouped["change"] = grouped[metric].diff()
    previous = grouped[metric].shift(1)
    grouped["change_percentage"] = ((grouped[metric] - previous) / previous.replace(0, pd.NA) * 100).round(2)
    return _records(grouped)


def compare_periods(frame: pd.DataFrame, metric: str, date_column: str, mode: str = "month", aggregation: str = "sum") -> dict[str, Any]:
    rows = trend(frame, metric, date_column, mode, aggregation)
    if len(rows) < 2:
        raise AppError("At least two periods are required for comparison.", "INSUFFICIENT_PERIODS")
    previous, current = rows[-2], rows[-1]
    previous_value, current_value = previous[metric], current[metric]
    change = current_value - previous_value
    percentage = None if previous_value == 0 else round(change / previous_value * 100, 2)
    return {"current_period": current["Period"], "previous_period": previous["Period"], "current_value": current_value, "previous_value": previous_value, "change": change, "change_percentage": percentage}


def compare_periods_by_group(frame: pd.DataFrame, metric: str, date_column: str, group: str, mode: str, aggregation: str, sort: str, limit: int) -> list[dict[str, Any]]:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[metric], errors="coerce")
    frequencies = {"month": "M", "quarter": "Q", "year": "Y"}
    working = pd.DataFrame({"Period": dates.dt.to_period(frequencies[mode]).astype("string"), group: frame[group], metric: values}).dropna()
    periods = sorted(working["Period"].unique())
    if len(periods) < 2:
        raise AppError("At least two periods are required for comparison.", "INSUFFICIENT_PERIODS")
    previous_period, current_period = periods[-2], periods[-1]
    pivot = working[working["Period"].isin([previous_period, current_period])].pivot_table(index=group, columns="Period", values=metric, aggfunc=aggregation, fill_value=0)
    for period in (previous_period, current_period):
        if period not in pivot.columns: pivot[period] = 0
    pivot["previous_value"] = pivot[previous_period]
    pivot["current_value"] = pivot[current_period]
    pivot["change"] = pivot["current_value"] - pivot["previous_value"]
    pivot["change_percentage"] = (pivot["change"] / pivot["previous_value"].replace(0, pd.NA) * 100).round(2)
    result = pivot.reset_index()[[group, "previous_value", "current_value", "change", "change_percentage"]].sort_values("change_percentage", ascending=sort == "asc").head(limit)
    return _records(result)
