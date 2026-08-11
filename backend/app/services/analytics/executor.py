from typing import Any

import pandas as pd
import calendar

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, FilterCondition
from app.utils.dates import relative_date_range
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.semantics import validate_semantic_plan

NUMERIC_AGGREGATIONS = {"sum", "mean", "min", "max", "median"}
DATE_OPERATIONS = {"trend", "compare_periods", "running_total", "percentage_change", "moving_average", "consecutive_growth", "consecutive_decline"}


def _value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def validate_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> None:
    columns = set(map(str, frame.columns))
    sort_columns = [item.column for item in plan.sort] if isinstance(plan.sort, list) else []
    referenced = ([plan.metric] if plan.metric else []) + ([plan.secondary_metric] if plan.secondary_metric else []) + plan.group_by + plan.partition_by + ([plan.date_column] if plan.date_column else []) + ([plan.date_filter.column] if plan.date_filter else []) + [item.column for item in plan.filters] + sort_columns
    missing = [column for column in referenced if column not in columns]
    if missing:
        raise AppError(f"Column '{missing[0]}' was not found.", "COLUMN_NOT_FOUND")
    validate_semantic_plan(profile_dataset(frame, "validation")["columns"], plan)
    needs_metric = plan.operation not in {"count", "filter", "sort", "distinct_count", "pipeline"}
    if needs_metric and not plan.metric:
        raise AppError("This operation requires a metric column.", "INVALID_QUERY_PLAN")
    if plan.operation == "distinct_count" and not (plan.metric or plan.group_by):
        raise AppError("Distinct count requires a column.", "INVALID_QUERY_PLAN")
    if plan.aggregation in NUMERIC_AGGREGATIONS and plan.metric and not pd.api.types.is_numeric_dtype(frame[plan.metric]):
        converted = pd.to_numeric(frame[plan.metric], errors="coerce")
        if converted.notna().sum() == 0:
            raise AppError(f"Column '{plan.metric}' is not numeric.", "INVALID_AGGREGATION")
    if plan.operation in {"group_and_aggregate", "top_n", "bottom_n", "compare_groups", "percent_of_total", "contribution", "rank", "variance", "compare_segments", "consecutive_growth", "consecutive_decline"} and not plan.group_by:
        raise AppError("This operation requires a group-by column.", "INVALID_QUERY_PLAN")
    if plan.operation == "correlation" and not plan.secondary_metric:
        raise AppError("Correlation requires a secondary metric.", "INVALID_QUERY_PLAN")
    if plan.operation in DATE_OPERATIONS:
        if not plan.date_column:
            raise AppError("This operation requires a date column.", "INVALID_DATE_COLUMN")
        parsed = pd.to_datetime(frame[plan.date_column], errors="coerce")
        if parsed.notna().sum() == 0:
            raise AppError(f"Column '{plan.date_column}' is not date-compatible.", "INVALID_DATE_COLUMN")
    if plan.operation == "pipeline":
        if not plan.steps:
            raise AppError("A pipeline requires at least one step.", "INVALID_QUERY_PLAN")
        if plan.steps[0].operation != "trend":
            raise AppError("Pipelines must begin with a trend step.", "INVALID_QUERY_PLAN")


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
        if operator == "is_null": return series.isna()
        if operator == "is_not_null": return series.notna()
        if operator == "equals": return text.str.casefold() == str(value).casefold()
        if operator == "not_equals": return text.str.casefold() != str(value).casefold()
        if operator == "contains":
            month_names = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
            if str(value).casefold() in month_names:
                parsed = pd.to_datetime(series, errors="coerce")
                if parsed.notna().any():
                    return parsed.dt.month == month_names[str(value).casefold()]
            return text.str.contains(str(value), case=False, regex=False, na=False)
        if operator == "not_contains": return ~text.str.contains(str(value), case=False, regex=False, na=False)
        if operator == "starts_with": return text.str.startswith(str(value), na=False)
        if operator == "ends_with": return text.str.endswith(str(value), na=False)
        if operator == "in": return text.str.casefold().isin([str(item).casefold() for item in value])
        if operator == "not_in": return ~text.str.casefold().isin([str(item).casefold() for item in value])
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
    if plan.date_filter:
        start, end = relative_date_range(plan.date_filter.period)
        dates = pd.to_datetime(working[plan.date_filter.column], errors="coerce", format="mixed")
        working = working.loc[(dates >= start) & (dates < end)]
    if plan.operation == "count":
        return {"count": int(len(working))}
    if plan.operation == "distinct_count":
        column = plan.metric or plan.group_by[0]
        return {"column": column, "distinct_count": int(working[column].nunique(dropna=True))}
    if plan.operation == "filter":
        return _records(working.head(plan.limit))
    if plan.operation == "sort":
        if isinstance(plan.sort, list):
            return _records(working.sort_values([rule.column for rule in plan.sort], ascending=[rule.direction == "asc" for rule in plan.sort]).head(plan.limit))
        column = plan.metric or plan.group_by[0]
        return _records(working.sort_values(column, ascending=plan.sort != "desc").head(plan.limit))
    if plan.operation == "aggregate":
        aggregation = plan.aggregation or "sum"
        return {"metric": plan.metric, "aggregation": aggregation, "value": _aggregate(working[plan.metric], aggregation)}
    if plan.operation == "trend":
        return trend(working, plan.metric, plan.date_column, plan.time_granularity or "month", plan.aggregation or "sum", plan.group_by)
    if plan.operation == "compare_periods":
        if plan.group_by:
            direction = plan.sort if isinstance(plan.sort, str) else "asc"
            return compare_periods_by_group(working, plan.metric, plan.date_column, plan.group_by[0], plan.period_mode or "month", plan.aggregation or "sum", direction or "asc", plan.limit)
        return compare_periods(working, plan.metric, plan.date_column, plan.period_mode or "month", plan.aggregation or "sum")
    if plan.operation == "correlation":
        first = pd.to_numeric(working[plan.metric], errors="coerce")
        second = pd.to_numeric(working[plan.secondary_metric], errors="coerce")
        return {"metric": plan.metric, "secondary_metric": plan.secondary_metric, "correlation": _value(first.corr(second))}
    if plan.operation == "compare_segments" and plan.secondary_metric and plan.date_column and plan.group_by:
        primary = compare_periods_by_group(working, plan.metric, plan.date_column, plan.group_by[0], plan.period_mode or "month", plan.aggregation or "sum", "desc", 100)
        secondary = compare_periods_by_group(working, plan.secondary_metric, plan.date_column, plan.group_by[0], plan.period_mode or "month", plan.secondary_aggregation or "mean", "asc", 100)
        secondary_by_group = {row[plan.group_by[0]]: row for row in secondary}
        rows = []
        for row in primary:
            other = secondary_by_group.get(row[plan.group_by[0]])
            if other and row["change"] > 0 and other["change"] < 0:
                rows.append({plan.group_by[0]: row[plan.group_by[0]], f"{plan.metric}_change": row["change"], f"{plan.metric}_change_percentage": row["change_percentage"], f"{plan.secondary_metric}_change": other["change"], f"{plan.secondary_metric}_change_percentage": other["change_percentage"]})
        return rows[:plan.limit]
    if plan.operation == "pipeline":
        return execute_pipeline(working, plan)
    if plan.operation in {"running_total", "percentage_change", "moving_average"}:
        rows = trend(working, plan.metric, plan.date_column, plan.time_granularity or "month", plan.aggregation or "sum", plan.group_by)
        data = pd.DataFrame(rows)
        partitions = plan.group_by
        if plan.operation == "running_total": data["running_total"] = data.groupby(partitions)[plan.metric].cumsum() if partitions else data[plan.metric].cumsum()
        elif plan.operation == "percentage_change": data["percentage_change"] = (data.groupby(partitions)[plan.metric].pct_change() if partitions else data[plan.metric].pct_change()).mul(100).round(2)
        else: data["moving_average"] = (data.groupby(partitions)[plan.metric].rolling(plan.window).mean().reset_index(level=partitions, drop=True) if partitions else data[plan.metric].rolling(plan.window).mean()).round(2)
        return _records(data.head(plan.limit))
    if plan.operation in {"consecutive_growth", "consecutive_decline"}:
        rows = trend(working, plan.metric, plan.date_column, plan.time_granularity or "month", plan.aggregation or "sum", plan.group_by)
        return consecutive(rows, plan.group_by[0], plan.metric, plan.periods, plan.operation == "consecutive_growth")[:plan.limit]
    groups = plan.group_by
    aggregation = plan.aggregation or "sum"
    if plan.compare_values:
        working = working[working[groups[0]].astype(str).str.casefold().isin([value.casefold() for value in plan.compare_values])]
    value_column = "count" if aggregation == "count" else plan.metric
    if aggregation == "count":
        grouped = working.groupby(groups, dropna=False).size().reset_index(name=value_column)
    elif plan.operation == "variance" and plan.date_column:
        dates = pd.to_datetime(working[plan.date_column], errors="coerce", format="mixed")
        monthly = working.assign(_period=dates.dt.to_period(plan.time_granularity[0].upper() if plan.time_granularity else "M")).groupby(groups + ["_period"])[plan.metric].sum().reset_index()
        grouped = monthly.groupby(groups, dropna=False)[plan.metric].var().reset_index()
    else:
        selected = working[groups + [plan.metric]].copy()
        selected[plan.metric] = pd.to_numeric(selected[plan.metric], errors="coerce")
        selected = selected.dropna(subset=[plan.metric])
        grouped = selected.groupby(groups, dropna=False)[plan.metric].agg("var" if plan.operation == "variance" else aggregation).reset_index()
    if plan.operation in {"percent_of_total", "contribution"}:
        total = grouped[value_column].sum()
        grouped["percentage_of_total"] = 0.0 if total == 0 else (grouped[value_column] / total * 100).round(2)
    if plan.operation == "rank":
        partitions = plan.partition_by or groups[:-1]
        grouped["rank"] = grouped.groupby(partitions)[value_column].rank(method="dense", ascending=False).astype(int) if partitions else grouped[value_column].rank(method="dense", ascending=False).astype(int)
        if partitions:
            grouped = grouped[grouped["rank"] <= plan.limit]
    ascending = plan.operation == "bottom_n" or plan.sort == "asc"
    if isinstance(plan.sort, list):
        grouped = grouped.sort_values([rule.column for rule in plan.sort], ascending=[rule.direction == "asc" for rule in plan.sort])
    elif plan.operation in {"top_n", "bottom_n"} or plan.sort:
        grouped = grouped.sort_values([value_column, *groups], ascending=[ascending, *([True] * len(groups))])
    return _records(grouped if plan.operation == "rank" and (plan.partition_by or groups[:-1]) else grouped.head(plan.limit))


def trend(frame: pd.DataFrame, metric: str, date_column: str, granularity: str = "month", aggregation: str = "sum", group_by: list[str] | None = None) -> list[dict[str, Any]]:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[metric], errors="coerce")
    groups = group_by or []
    working = pd.DataFrame({"date": dates, metric: values, **{group: frame[group] for group in groups}}).dropna(subset=["date", metric])
    frequencies = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
    working["Period"] = working["date"].dt.to_period(frequencies[granularity]).astype(str)
    grouped = working.groupby(groups + ["Period"])[metric].agg(aggregation).reset_index().sort_values(groups + ["Period"])
    grouped["change"] = grouped.groupby(groups)[metric].diff() if groups else grouped[metric].diff()
    previous = grouped.groupby(groups)[metric].shift(1) if groups else grouped[metric].shift(1)
    grouped["change_percentage"] = ((grouped[metric] - previous) / previous.replace(0, pd.NA) * 100).round(2)
    return _records(grouped)


def consecutive(rows: list[dict[str, Any]], group: str, metric: str, periods: int, growth: bool) -> list[dict[str, Any]]:
    frame = pd.DataFrame(rows)
    results: list[dict[str, Any]] = []
    for value, part in frame.groupby(group):
        changes = part.sort_values("Period")[metric].diff()
        flags = changes.gt(0) if growth else changes.lt(0)
        streak = maximum_streak(flags.fillna(False).tolist())
        if streak >= periods:
            results.append({group: _value(value), "consecutive_periods": streak, "latest_value": _value(part.sort_values("Period")[metric].iloc[-1])})
    return sorted(results, key=lambda item: item["consecutive_periods"], reverse=True)


def maximum_streak(flags: list[bool]) -> int:
    maximum = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        maximum = max(maximum, current)
    return maximum


def execute_pipeline(frame: pd.DataFrame, plan: AnalysisPlan) -> Any:
    first = plan.steps[0]
    rows = trend(frame, first.metric or plan.metric, first.date_column or plan.date_column, first.time_granularity or "month", plan.aggregation or "sum", first.group_by or plan.group_by)
    result: Any = rows
    for step in plan.steps[1:]:
        if step.operation == "calculate_change":
            data = pd.DataFrame(result)
            groups = first.group_by or plan.group_by
            data["percentage_change"] = (data.groupby(groups)[first.metric or plan.metric].pct_change() if groups else data[first.metric or plan.metric].pct_change()).mul(100).round(2)
            result = _records(data)
        elif step.operation in {"consecutive_growth", "consecutive_decline"}:
            groups = first.group_by or plan.group_by
            if not groups: raise AppError("Consecutive analysis requires a group.", "INVALID_QUERY_PLAN")
            result = consecutive(rows, groups[0], first.metric or plan.metric, step.periods, step.operation == "consecutive_growth")
        elif step.operation == "moving_average":
            data = pd.DataFrame(result); groups = first.group_by or plan.group_by; metric = first.metric or plan.metric
            data["moving_average"] = (data.groupby(groups)[metric].rolling(step.window).mean().reset_index(level=groups, drop=True) if groups else data[metric].rolling(step.window).mean()).round(2); result = _records(data)
        elif step.operation == "rank":
            data = pd.DataFrame(result); metric = first.metric or plan.metric; data["rank"] = data[metric].rank(method="dense", ascending=False).astype(int); result = _records(data.sort_values("rank"))
    return result[:plan.limit] if isinstance(result, list) else result


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
