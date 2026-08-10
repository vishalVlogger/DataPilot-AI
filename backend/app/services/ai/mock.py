import calendar
import re
from typing import Any

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, DateFilter, FilterCondition, PipelineStep
from app.services.ai.base import AIProvider


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _singular(text: str) -> str:
    return text[:-1] if text.endswith("s") and len(text) > 3 else text


def _find_column(question: str, names: list[str], allowed: set[str] | None = None) -> str | None:
    words = {_singular(word) for word in _normalized(question).split()}
    candidates = [name for name in names if allowed is None or name in allowed]
    matches = []
    for name in candidates:
        tokens = {_singular(word) for word in _normalized(name).split()}
        if tokens and tokens.issubset(words):
            matches.append(name)
    return max(matches, key=len) if matches else None


class MockAIProvider(AIProvider):
    async def create_analysis_plan(self, question: str, columns: list[dict[str, Any]]) -> AnalysisPlan:
        names = [item["name"] for item in columns]
        numeric = {item["name"] for item in columns if item["category"] == "numeric"}
        dates = {item["name"] for item in columns if item["category"] == "date"}
        categorical = {item["name"] for item in columns if item["category"] in {"categorical", "boolean"}}
        default_metric = next((name for name in names if name in numeric), None)
        default_date = next((name for name in names if name in dates), None)
        q = _normalized(question)
        metric = _find_column(question, names, numeric)
        date_column = _find_column(question, names, dates) or default_date
        group = _find_column(question, names, categorical)
        if not group:
            question_folded = f" {q.casefold()} "
            group = next((item["name"] for item in columns if item["name"] in categorical and any(len(_normalized(str(value))) >= 2 and f" {_normalized(str(value))} " in question_folded for value in item.get("sample_values", []) if str(value).strip())), None)
        aggregation = "mean" if re.search(r"\b(average|mean)\b", q) else "median" if "median" in q else "min" if re.search(r"\b(minimum|min)\b", q) else "max" if re.search(r"\b(maximum|max)\b", q) else "sum"

        consecutive_match = re.search(r"(declined|decreased|grew|increased).+?(\d+)\s+consecutive\s+months", q)
        if consecutive_match and group and date_column:
            periods = int(consecutive_match.group(2))
            direction = "consecutive_decline" if consecutive_match.group(1) in {"declined", "decreased"} else "consecutive_growth"
            return AnalysisPlan(operation="pipeline", metric=metric or default_metric, group_by=[group], date_column=date_column, limit=100, steps=[PipelineStep(operation="trend", metric=metric or default_metric, group_by=[group], date_column=date_column, time_granularity="month"), PipelineStep(operation=direction, periods=periods)])

        if "moving average" in q and date_column:
            window_match = re.search(r"(\d+)[ -](?:month|period)", q)
            return AnalysisPlan(operation="moving_average", metric=metric or default_metric, date_column=date_column, time_granularity="month", window=int(window_match.group(1)) if window_match else 3, limit=100)

        if "increased" in q and "decreased" in q and group and date_column:
            mentioned_numeric = [name for name in names if name in numeric and _find_column(question, [name])]
            if len(mentioned_numeric) >= 2:
                return AnalysisPlan(operation="compare_segments", metric=mentioned_numeric[0], secondary_metric=mentioned_numeric[1], aggregation="sum", secondary_aggregation="mean", group_by=[group], date_column=date_column, period_mode="month", limit=100)

        if "contribution" in q or "percent of total" in q or "percentage of total" in q:
            if not group: raise AppError("Contribution analysis requires a category.", "AMBIGUOUS_QUESTION")
            contribution_limit = re.search(r"top\s+(\d+)", q)
            return AnalysisPlan(operation="contribution", metric=metric or default_metric, aggregation="sum", group_by=[group], sort="desc", limit=int(contribution_limit.group(1)) if contribution_limit else 100)

        if "rank" in q and group:
            mentioned_groups = [name for name in names if name in categorical and _find_column(question, [name])]
            if len(mentioned_groups) >= 2:
                return AnalysisPlan(operation="rank", metric=metric or default_metric, aggregation="sum", group_by=mentioned_groups, partition_by=[mentioned_groups[0]], limit=100)
            return AnalysisPlan(operation="rank", metric=metric or default_metric, aggregation="sum", group_by=[group], limit=100)

        each_match = re.search(r"top\s+(\d+).+?in each", q)
        if each_match:
            mentioned_groups = [name for name in names if name in categorical and _find_column(question, [name])]
            if len(mentioned_groups) >= 2:
                return AnalysisPlan(operation="rank", metric=metric or default_metric, aggregation="sum", group_by=mentioned_groups, partition_by=[mentioned_groups[0]], limit=int(each_match.group(1)))

        if "variance" in q and group:
            return AnalysisPlan(operation="variance", metric=metric or default_metric, aggregation="sum", group_by=[group], date_column=date_column if "month" in q else None, time_granularity="month" if "month" in q else None, sort="desc", limit=100)

        if "correlation" in q:
            mentioned_numeric = [name for name in names if name in numeric and _find_column(question, [name])]
            if len(mentioned_numeric) >= 2:
                return AnalysisPlan(operation="correlation", metric=mentioned_numeric[0], secondary_metric=mentioned_numeric[1])

        if re.search(r"\b(q1.+q2|q2.+q1)\b", q) and date_column:
            return AnalysisPlan(operation="trend", metric=metric or default_metric, aggregation=aggregation, group_by=[group] if group else [], date_column=date_column, time_granularity="quarter", limit=100)

        relative = next(((phrase, period) for phrase, period in [("last 3 months", "last_3_months"), ("last 6 months", "last_6_months"), ("last 12 months", "last_12_months"), ("this month", "this_month"), ("previous month", "previous_month"), ("this quarter", "this_quarter"), ("previous quarter", "previous_quarter"), ("this year", "this_year"), ("previous year", "previous_year")] if phrase in q), None)
        if relative and date_column and group:
            filters: list[FilterCondition] = []
            for item in columns:
                if item["name"] in categorical:
                    value = next((str(value) for value in item.get("sample_values", []) if len(_normalized(str(value))) >= 2 and f" {_normalized(str(value))} " in f" {q} "), None)
                    if value and item["name"] != group: filters.append(FilterCondition(column=item["name"], operator="equals", value=value))
            above = re.search(r"(?:above|greater than)\s+([\d,.]+)", q)
            if above and (metric or default_metric): filters.append(FilterCondition(column=metric or default_metric, operator="greater_than", value=float(above.group(1).replace(",", ""))))
            return AnalysisPlan(operation="group_and_aggregate", metric=metric or default_metric, aggregation=aggregation, group_by=[group], filters=filters, date_filter=DateFilter(column=date_column, period=relative[1]), sort="desc", limit=100)

        if re.search(r"\b(how many rows|row count|count rows|number of rows)\b", q):
            return AnalysisPlan(operation="count", aggregation="count")
        if re.search(r"\b(unique|distinct)\b", q):
            column = _find_column(question, names)
            if not column:
                raise AppError("Please name the column to count uniquely.", "AMBIGUOUS_QUESTION")
            return AnalysisPlan(operation="distinct_count", metric=column, aggregation="count")
        if re.search(r"\b(this|current) (month|quarter|year)\b", q) and re.search(r"\b(previous|last) (month|quarter|year)\b", q):
            mode = next(item for item in ("month", "quarter", "year") if item in q)
            return AnalysisPlan(operation="compare_periods", metric=metric or default_metric, aggregation=aggregation, date_column=date_column, period_mode=mode)
        if re.search(r"\b(monthly|weekly|daily|quarterly|yearly|trend|by month|by week|by quarter|by year|which month|what month)\b", q):
            granularities = {"daily": "day", "weekly": "week", "monthly": "month", "quarterly": "quarter", "yearly": "year"}
            granularity = next((value for word, value in granularities.items() if word in q), None)
            if not granularity:
                granularity = next((item for item in ("month", "week", "quarter", "year", "day") if f"by {item}" in q), "month")
            return AnalysisPlan(operation="trend", metric=metric or default_metric, aggregation=aggregation, date_column=date_column, time_granularity=granularity, limit=100)

        if re.search(r"\b(declined|decreased|grew|increased)\b", q) and group and date_column:
            return AnalysisPlan(operation="compare_periods", metric=metric or default_metric, aggregation="sum", group_by=[group], date_column=date_column, period_mode="month", sort="asc" if re.search(r"\b(declined|decreased)\b", q) else "desc", limit=1)

        scatter_match = re.search(r"(?:plot|scatter|show)\s+(.+?)\s+(?:vs|versus|against)\s+(.+?)(?:\s+chart)?$", question, re.I)
        if scatter_match:
            x_column = _find_column(scatter_match.group(1), names, numeric)
            y_column = _find_column(scatter_match.group(2), names, numeric)
            if x_column and y_column:
                return AnalysisPlan(operation="filter", metric=y_column, group_by=[x_column], limit=100)

        limit_match = re.search(r"\b(?:top|bottom)\s+(\d+)\b", q)
        if "top" in q or "bottom" in q:
            if not group:
                raise AppError("Please name the category to group by, such as product or region.", "AMBIGUOUS_QUESTION")
            return AnalysisPlan(operation="top_n" if "top" in q else "bottom_n", metric=metric or default_metric, group_by=[group], aggregation=aggregation, sort="desc" if "top" in q else "asc", limit=int(limit_match.group(1)) if limit_match else 10)
        if "compare" in q and group:
            text = re.search(r"compare\s+(.+?)\s+(?:and|with|vs)\s+(.+?)(?:\s+(?:sales|revenue|profit|by)|$)", question, re.I)
            values = [text.group(1).strip(), text.group(2).strip()] if text else []
            return AnalysisPlan(operation="compare_groups", metric=metric or default_metric, group_by=[group], aggregation=aggregation, compare_values=values, limit=20)

        comparison = re.search(r"\b(?:where|with)\s+(.+?)\s+(?:is\s+)?(above|greater than|at least|below|less than|at most|equals?)\s+([\d,.]+)", question, re.I)
        if comparison:
            filter_column = _find_column(comparison.group(1), names) or metric
            operators = {"above": "greater_than", "greater than": "greater_than", "at least": "greater_than_or_equal", "below": "less_than", "less than": "less_than", "at most": "less_than_or_equal", "equal": "equals", "equals": "equals"}
            condition = FilterCondition(column=filter_column or "", operator=operators[comparison.group(2).lower()], value=float(comparison.group(3).replace(",", "")))
            return AnalysisPlan(operation="filter", filters=[condition], limit=100)

        month = next((name for name in calendar.month_name[1:] if name.lower() in q), None)
        if month and metric and date_column:
            return AnalysisPlan(operation="aggregate", metric=metric, aggregation=aggregation, filters=[FilterCondition(column=date_column, operator="contains", value=month)])

        if group and (" by " in f" {q} " or aggregation == "mean"):
            return AnalysisPlan(operation="group_and_aggregate", metric=metric or default_metric, group_by=[group], aggregation=aggregation, sort="desc", limit=100)

        operations = [("average", "mean"), ("mean", "mean"), ("median", "median"), ("minimum", "min"), ("lowest", "min"), ("maximum", "max"), ("highest", "max"), ("total", "sum"), ("sum", "sum")]
        selected_aggregation = next((value for keyword, value in operations if keyword in q), None)
        if selected_aggregation:
            if not metric:
                raise AppError("Please include the numeric column you want to analyze.", "AMBIGUOUS_QUESTION")
            return AnalysisPlan(operation="aggregate", metric=metric, aggregation=selected_aggregation)
        if re.search(r"\b(count|how many)\b", q):
            return AnalysisPlan(operation="count", aggregation="count")
        raise AppError("Supported questions include aggregation, grouping, filters, distinct counts, rankings, trends, and period comparisons.", "UNSUPPORTED_QUESTION")

    async def explain_result(self, question: str, plan: AnalysisPlan, result: Any) -> str:
        if plan.operation == "count":
            return f"The filtered dataset contains {result['count']:,} rows."
        if plan.operation == "distinct_count":
            return f"{result['column']} contains {result['distinct_count']:,} distinct values."
        if plan.operation == "aggregate":
            labels = {"sum": "total", "mean": "average", "median": "median", "min": "minimum", "max": "maximum", "count": "count"}
            value = result["value"]
            rendered = f"{value:,.2f}" if isinstance(value, (float, int)) else str(value)
            return f"The {labels.get(plan.aggregation, plan.aggregation)} {plan.metric} is {rendered}."
        if plan.operation == "compare_periods":
            if isinstance(result, list):
                if not result:
                    return "No comparable groups were found across the latest two periods."
                row = result[0]
                group = plan.group_by[0]
                direction = "declined" if row["change"] < 0 else "grew"
                return f"{row[group]} {direction} the most, changing by {abs(row['change_percentage'] or 0):.2f}% across the latest two periods."
            direction = "increased" if result["change"] >= 0 else "decreased"
            percent = "not defined because the previous value was zero" if result["change_percentage"] is None else f"{abs(result['change_percentage']):.2f}%"
            return f"{plan.metric} {direction} by {percent}, from {result['previous_value']:,.2f} to {result['current_value']:,.2f}."
        if plan.operation == "filter":
            return f"{len(result):,} matching rows are shown."
        if plan.operation == "trend":
            if result and re.search(r"\b(highest|strongest|best)\b", question, re.I):
                strongest = max(result, key=lambda row: row[plan.metric])
                return f"{strongest['Period']} had the highest {plan.metric} at {strongest[plan.metric]:,.2f}."
            return f"Calculated {len(result):,} {plan.time_granularity} periods for {plan.metric}."
        direction = "top" if plan.operation == "top_n" else "bottom" if plan.operation == "bottom_n" else "grouped"
        group = ", ".join(plan.group_by)
        return f"Here are {len(result):,} {direction} {group} results calculated from {plan.metric}."
