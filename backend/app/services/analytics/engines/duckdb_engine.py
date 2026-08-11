from time import perf_counter
from typing import Any
from pathlib import Path

import duckdb
import pandas as pd

from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan, FilterCondition
from app.services.analytics.engines.base import AnalyticsExecutionEngine, EngineResult
from app.services.analytics.executor import execute_plan, validate_plan
from app.utils.dates import relative_date_range


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _where(plan: AnalysisPlan) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    operators = {"equals": "=", "not_equals": "!=", "greater_than": ">", "greater_than_or_equal": ">=", "less_than": "<", "less_than_or_equal": "<=", "before": "<", "after": ">"}
    for item in plan.filters:
        column = _identifier(item.column)
        if item.operator in operators:
            clauses.append(f"{column} {operators[item.operator]} ?"); params.append(item.value)
        elif item.operator == "between":
            clauses.append(f"{column} BETWEEN ? AND ?"); params.extend(item.value)
        elif item.operator in {"in", "not_in"}:
            placeholders = ",".join("?" for _ in item.value)
            clauses.append(f"{column} {'NOT IN' if item.operator == 'not_in' else 'IN'} ({placeholders})"); params.extend(item.value)
        elif item.operator in {"is_null", "is_not_null"}:
            clauses.append(f"{column} IS {'NOT ' if item.operator == 'is_not_null' else ''}NULL")
        elif item.operator in {"contains", "not_contains", "starts_with", "ends_with"}:
            raw = str(item.value).replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{raw}%" if "contains" in item.operator else f"{raw}%" if item.operator == "starts_with" else f"%{raw}"
            clauses.append(f"CAST({column} AS VARCHAR) {'NOT ' if item.operator == 'not_contains' else ''}ILIKE ? ESCAPE '\\'"); params.append(pattern)
        else:
            raise AppError("Unsupported DuckDB filter.", "INVALID_FILTER")
    if plan.date_filter:
        start, end = relative_date_range(plan.date_filter.period)
        column = _identifier(plan.date_filter.column)
        clauses.append(f"TRY_CAST({column} AS TIMESTAMP) >= ? AND TRY_CAST({column} AS TIMESTAMP) < ?")
        params.extend([start.to_pydatetime(), end.to_pydatetime()])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


class DuckDBExecutionEngine(AnalyticsExecutionEngine):
    name = "duckdb"
    sql_operations = {"aggregate", "group_and_aggregate", "filter", "sort", "top_n", "bottom_n", "count", "distinct_count", "trend", "compare_periods", "compare_groups", "percent_of_total", "contribution", "rank", "variance", "compare_segments"}

    async def execute_plan(self, dataset: pd.DataFrame | Path, plan: AnalysisPlan) -> EngineResult:
        started = perf_counter()
        if plan.operation not in self.sql_operations:
            frame = pd.read_parquet(dataset) if isinstance(dataset, Path) else dataset
            result = execute_plan(frame, plan)
            return EngineResult(result=result, engine="pandas_fallback", duration_ms=round((perf_counter() - started) * 1000, 3))
        connection = duckdb.connect(database=":memory:")
        try:
            if isinstance(dataset, Path):
                connection.from_parquet(str(dataset)).create_view("dataset")
                validation_sample = connection.execute("SELECT * FROM dataset LIMIT 1000").fetchdf()
            else:
                connection.register("dataset", dataset)
                validation_sample = dataset
            validate_plan(validation_sample, plan)
            result = self._execute(connection, plan)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("DuckDB could not execute the validated plan.", "EXECUTION_ENGINE_FAILED", 500) from exc
        finally:
            connection.close()
        return EngineResult(result=result, engine=self.name, duration_ms=round((perf_counter() - started) * 1000, 3))

    def _execute(self, connection: duckdb.DuckDBPyConnection, plan: AnalysisPlan) -> Any:
        where, params = _where(plan)
        metric = _identifier(plan.metric) if plan.metric else None
        if plan.operation == "count":
            return {"count": int(connection.execute(f"SELECT COUNT(*) FROM dataset{where}", params).fetchone()[0])}
        if plan.operation == "distinct_count":
            column_name = plan.metric or plan.group_by[0]; column = _identifier(column_name)
            return {"column": column_name, "distinct_count": int(connection.execute(f"SELECT COUNT(DISTINCT {column}) FROM dataset{where}", params).fetchone()[0])}
        if plan.operation == "filter":
            return connection.execute(f"SELECT * FROM dataset{where} LIMIT ?", params + [plan.limit]).fetchdf().to_dict(orient="records")
        if plan.operation == "sort":
            rules = plan.sort if isinstance(plan.sort, list) else []
            if rules: order = ", ".join(f"{_identifier(rule.column)} {rule.direction.upper()}" for rule in rules)
            else: order = f"{_identifier(plan.metric or plan.group_by[0])} {'DESC' if plan.sort == 'desc' else 'ASC'}"
            return connection.execute(f"SELECT * FROM dataset{where} ORDER BY {order} LIMIT ?", params + [plan.limit]).fetchdf().to_dict(orient="records")
        aggregates = {"sum": "SUM", "mean": "AVG", "min": "MIN", "max": "MAX", "count": "COUNT", "median": "MEDIAN"}
        aggregate = aggregates[plan.aggregation or "sum"]
        if plan.operation == "aggregate":
            expression = "COUNT(*)" if aggregate == "COUNT" else f"{aggregate}(TRY_CAST({metric} AS DOUBLE))"
            value = connection.execute(f"SELECT {expression} FROM dataset{where}", params).fetchone()[0]
            return {"metric": plan.metric, "aggregation": plan.aggregation or "sum", "value": value}
        if plan.operation == "trend":
            grains = {"day": "day", "week": "week", "month": "month", "quarter": "quarter", "year": "year"}
            groups = plan.group_by
            select_groups = ", ".join(_identifier(group) for group in groups)
            prefix = f"{select_groups}, " if groups else ""
            date = _identifier(plan.date_column)
            sql = f"SELECT {prefix}strftime(date_trunc('{grains[plan.time_granularity or 'month']}', TRY_CAST({date} AS TIMESTAMP)), '%Y-%m-%d') AS Period, {aggregate}(TRY_CAST({metric} AS DOUBLE)) AS {metric} FROM dataset{where} GROUP BY {prefix}Period ORDER BY {prefix}Period"
            return connection.execute(sql, params).fetchdf().to_dict(orient="records")
        if plan.operation == "compare_periods" and not plan.group_by:
            trend_plan = plan.model_copy(update={"operation": "trend", "time_granularity": plan.period_mode or "month"})
            rows = self._execute(connection, trend_plan)
            if len(rows) < 2:
                raise AppError("At least two periods are required for comparison.", "INSUFFICIENT_PERIODS")
            previous, current = rows[-2], rows[-1]; previous_value = previous[plan.metric]; current_value = current[plan.metric]; change = current_value - previous_value
            return {"current_period": current["Period"], "previous_period": previous["Period"], "current_value": current_value, "previous_value": previous_value, "change": change, "change_percentage": None if previous_value == 0 else round(change / previous_value * 100, 2)}
        groups = plan.group_by
        group_sql = ", ".join(_identifier(group) for group in groups)
        value_expression = f"VAR_SAMP(TRY_CAST({metric} AS DOUBLE))" if plan.operation == "variance" else "COUNT(*)" if aggregate == "COUNT" else f"{aggregate}(TRY_CAST({metric} AS DOUBLE))"
        base = f"SELECT {group_sql}, {value_expression} AS {metric} FROM dataset{where} GROUP BY {group_sql}"
        if plan.operation in {"percent_of_total", "contribution"}:
            sql = f"WITH grouped AS ({base}) SELECT *, CASE WHEN SUM({metric}) OVER () = 0 THEN 0 ELSE ROUND({metric} / SUM({metric}) OVER () * 100, 2) END AS percentage_of_total FROM grouped"
        elif plan.operation == "rank":
            partitions = plan.partition_by or groups[:-1]
            partition = f"PARTITION BY {', '.join(_identifier(item) for item in partitions)} " if partitions else ""
            sql = f"WITH grouped AS ({base}) SELECT *, DENSE_RANK() OVER ({partition}ORDER BY {metric} DESC) AS rank FROM grouped"
        else: sql = base
        if isinstance(plan.sort, list): order = ", ".join(f"{_identifier(rule.column)} {rule.direction.upper()}" for rule in plan.sort)
        else: order = f"{metric} {'ASC' if plan.operation == 'bottom_n' or plan.sort == 'asc' else 'DESC'}"
        sql += f" ORDER BY {order} LIMIT ?"
        return connection.execute(sql, params + [plan.limit]).fetchdf().to_dict(orient="records")
