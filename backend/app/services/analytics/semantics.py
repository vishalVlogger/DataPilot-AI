import calendar
import re
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

from app.core.errors import AppError

SemanticRole = Literal[
    "measure", "categorical_dimension", "temporal_dimension", "identifier",
    "high_cardinality_dimension", "boolean_dimension", "unknown",
]

ROLE_AGGREGATIONS: dict[SemanticRole, list[str]] = {
    "measure": ["sum", "average", "median", "min", "max", "count"],
    "categorical_dimension": ["count", "distinct_count"],
    "temporal_dimension": ["min", "max", "count", "distinct_count"],
    "identifier": ["count", "distinct_count"],
    "high_cardinality_dimension": ["count", "distinct_count"],
    "boolean_dimension": ["count", "distinct_count"],
    "unknown": ["count", "distinct_count"],
}

YEAR_NAMES = {
    "year", "model_year", "manufacture_year", "manufacturing_year",
    "registration_year", "registered_year", "production_year", "built_year",
}
TEMPORAL_HELPER_NAMES: dict[str, set[str]] = {
    "month": {"month", "month_number", "month_no", "month_num", "fiscal_month"},
    "quarter": {"quarter", "quarter_number", "quarter_no", "quarter_num", "fiscal_quarter"},
    "week": {"week", "week_number", "week_no", "week_num", "fiscal_week"},
    "day": {"day_of_week", "day_number", "day_no", "day_num"},
}
TEMPORAL_HELPER_RANGES = {"month": (1, 12), "quarter": (1, 4), "week": (1, 53), "day": (1, 31)}
TEMPORAL_DISPLAY_NAMES = {
    "month": {"month", "month_name", "month_label"},
    "quarter": {"quarter", "quarter_name", "quarter_label"},
    "week": {"week", "week_name", "week_label"},
}
MONTH_ORDER = {name.casefold(): index for index, name in enumerate(calendar.month_name) if name}
MONTH_ORDER.update({name.casefold(): index for index, name in enumerate(calendar.month_abbr) if name})
ID_TOKENS = {"id", "identifier", "invoice", "transaction", "serial", "registration", "account", "customer", "order"}
ID_SUFFIXES = ("_id", " id", "_number", " number", "_no", " no", "_code")
BOOLEAN_NAMES = {"active", "enabled", "disabled", "flag", "is_active", "is_deleted", "success", "valid"}
SUM_LIKE = {"sales", "revenue", "amount", "profit", "quantity", "qty", "cost", "units", "volume", "total"}
AVERAGE_LIKE = {"price", "rate", "ratio", "percentage", "percent", "margin", "score", "age", "distance", "mileage", "km", "temperature"}
RANKING_MEASURE_HINTS: list[tuple[set[str], set[str], str]] = [
    ({"most", "expensive"}, {"price", "cost", "amount"}, "max"),
    ({"cheapest"}, {"price", "cost", "amount"}, "min"),
    ({"most", "profitable"}, {"profit", "margin"}, "sum"),
    ({"best", "selling"}, {"sales", "revenue", "units", "sold", "volume"}, "sum"),
]


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def natural_label(name: str) -> str:
    """Convert a schema identifier to a stable, presentation-only label."""
    return _normalized(name).replace("_", " ").capitalize()


def _measure_matching(columns: list[dict[str, Any]], hints: set[str]) -> str | None:
    measures = [item for item in columns if item.get("semantic_role") == "measure"]
    scored = [
        (len(set(_normalized(item["name"]).split("_")) & hints), -index, item["name"])
        for index, item in enumerate(measures)
    ]
    best = max(scored, default=(0, 0, None))
    return best[2] if best[0] else None


def ranking_defaults(question: str, columns: list[dict[str, Any]], dimension: str, explicit_metric: str | None) -> tuple[str, str, bool]:
    """Resolve a ranking metric without falling back to the first numeric column."""
    words = set(_normalized(question).split("_"))
    if {"most", "common"} <= words:
        return dimension, "count", False
    for intent_words, hints, aggregation in RANKING_MEASURE_HINTS:
        if intent_words <= words:
            metric = _measure_matching(columns, hints)
            if metric:
                return metric, aggregation, False
    if explicit_metric:
        if {"average", "mean"} & words: aggregation = "mean"
        elif {"maximum", "max"} & words: aggregation = "max"
        elif {"minimum", "min"} & words: aggregation = "min"
        else:
            item = next(column for column in columns if column["name"] == explicit_metric)
            aggregation = preferred_automatic_aggregation(item)
        return explicit_metric, aggregation, False
    if "price" in words:
        metric = _measure_matching(columns, {"price", "cost", "amount"})
        if metric:
            return metric, "mean", True
    if "sales" in words or "selling" in words:
        metric = _measure_matching(columns, {"sales", "revenue", "units", "sold", "volume"})
        if metric:
            return metric, "sum", True
    measures = [item for item in columns if item.get("semantic_role") == "measure"]
    for hints, aggregation in [({"price", "cost"}, "mean"), ({"sales", "revenue", "units", "volume"}, "sum"), ({"profit", "margin"}, "sum")]:
        metric = _measure_matching(columns, hints)
        if metric:
            return metric, aggregation, True
    if len(measures) == 1:
        return measures[0]["name"], preferred_automatic_aggregation(measures[0]), True
    raise AppError(f"Ranked {natural_label(dimension).casefold()} by what metric?", "AMBIGUOUS_QUESTION")


def _physical_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series): return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series): return "datetime"
    if pd.api.types.is_integer_dtype(series): return "integer"
    if pd.api.types.is_numeric_dtype(series): return "number"
    return "string"


def temporal_helper_kind(name: str, series: pd.Series) -> tuple[str | None, float]:
    """Return a calendar-helper kind only when exact name and value shape agree."""
    normalized = _normalized(name)
    kind = next((candidate for candidate, names in TEMPORAL_HELPER_NAMES.items() if normalized in names), None)
    if kind is None: return None, 0.0
    clean = series.dropna()
    if clean.empty: return None, 0.0
    numeric = pd.to_numeric(clean, errors="coerce")
    numeric_ratio = float(numeric.notna().mean())
    numeric = numeric.dropna()
    if numeric.empty: return None, 0.0
    integer_ratio = float(((numeric % 1).abs() < 1e-9).mean())
    minimum, maximum = TEMPORAL_HELPER_RANGES[kind]
    range_ratio = float(numeric.between(minimum, maximum).mean())
    confidence = min(numeric_ratio, integer_ratio, range_ratio)
    return (kind, round(0.82 + 0.16 * confidence, 2)) if confidence >= 0.8 else (None, 0.0)


def temporal_value_order(value: Any, kind: str) -> tuple[int, str]:
    """Produce a deterministic chronological key for helper/display values."""
    text = str(value).strip().casefold()
    if kind == "month" and text in MONTH_ORDER: return MONTH_ORDER[text], text
    match = re.search(r"-?\d+", text)
    return (int(match.group()) if match else 10_000, text)


def temporal_axis_kind(name: str, columns: list[dict[str, Any]]) -> str | None:
    """Return the calendar grain represented by a chart axis, when known."""
    item = next((candidate for candidate in columns if candidate["name"] == name), {})
    return item.get("temporal_helper") or next(
        (kind for kind, names in TEMPORAL_DISPLAY_NAMES.items() if _normalized(name) in names),
        None,
    )


def sort_temporal_records(records: list[dict[str, Any]], x_axis: str, frame: pd.DataFrame, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort chart records by a helper column or a paired month-number field."""
    by_name = {item["name"]: item for item in columns}; item = by_name.get(x_axis, {})
    kind = temporal_axis_kind(x_axis, columns)
    mapping: dict[Any, int] = {}
    if item.get("temporal_helper") is None and kind:
        helper = next((candidate["name"] for candidate in columns if candidate.get("temporal_helper") == kind), None)
        if helper and x_axis in frame and helper in frame:
            paired = frame[[x_axis, helper]].dropna()
            mapping = {row[x_axis]: int(row[helper]) for _, row in paired.iterrows()}
    if kind is None: return records
    return sorted(records, key=lambda row: (mapping.get(row.get(x_axis), temporal_value_order(row.get(x_axis), kind)[0]), str(row.get(x_axis))))


def classify_column(
    name: str,
    series: pd.Series,
    *,
    year_min: int = 1900,
    year_tolerance: int = 2,
    high_cardinality_min_unique: int = 5,
    high_cardinality_ratio: float = 0.5,
) -> dict[str, Any]:
    clean = series.dropna(); rows = max(len(series), 1); unique = int(clean.nunique(dropna=True)); ratio = unique / max(len(clean), 1)
    normalized = _normalized(name); tokens = set(normalized.split("_")); physical = _physical_type(series)
    numeric = pd.to_numeric(clean, errors="coerce") if not clean.empty else pd.Series(dtype="float64")
    numeric_ratio = float(numeric.notna().mean()) if len(numeric) else 0.0
    current_year = datetime.now(timezone.utc).year
    plausible_year_ratio = float(numeric.between(year_min, current_year + year_tolerance).mean()) if len(numeric) else 0.0
    strong_year_name = normalized in YEAR_NAMES or normalized.endswith("_year")
    identifier_name = normalized in {"id", "uuid", "guid"} or normalized.endswith(ID_SUFFIXES) or bool(tokens & ID_TOKENS and tokens & {"id", "number", "no", "serial"})
    helper_kind, helper_confidence = temporal_helper_kind(name, series)
    boolean_values = {str(value).strip().casefold() for value in clean.unique()[:10]}
    boolean_like = physical == "boolean" or (unique <= 2 and (normalized in BOOLEAN_NAMES or boolean_values <= {"true", "false", "yes", "no", "y", "n", "0", "1"}))

    if boolean_like:
        role: SemanticRole = "boolean_dimension"; confidence = 0.98 if physical == "boolean" else 0.86
    elif helper_kind:
        role = "temporal_dimension"; confidence = helper_confidence
    elif strong_year_name and (plausible_year_ratio >= 0.6 or clean.empty):
        role = "temporal_dimension"; confidence = 0.98 if plausible_year_ratio >= 0.9 else 0.88
    elif physical == "datetime":
        role = "temporal_dimension"; confidence = 0.99
    elif identifier_name and (ratio >= 0.5 or unique >= 20):
        role = "identifier"; confidence = 0.96 if ratio >= 0.9 else 0.84
    elif physical == "string" and unique >= high_cardinality_min_unique and (ratio >= high_cardinality_ratio or unique >= 100):
        role = "high_cardinality_dimension"; confidence = min(0.97, 0.72 + ratio * 0.25)
    elif physical in {"integer", "number"} and numeric_ratio >= 0.9 and numeric.nunique() > 1:
        role = "measure"; confidence = 0.9 if any(token in SUM_LIKE | AVERAGE_LIKE for token in tokens) else 0.76
    elif physical == "string":
        role = "categorical_dimension"; confidence = 0.9 if unique > 1 else 0.7
    else:
        role = "unknown"; confidence = 0.5
    result = {
        "physical_type": physical, "semantic_role": role, "confidence": round(confidence, 2),
        "allowed_aggregations": ROLE_AGGREGATIONS[role], "uniqueness_ratio": round(ratio, 4),
    }
    if helper_kind: result["temporal_helper"] = helper_kind
    return result


def aggregation_allowed(column: dict[str, Any], aggregation: str | None) -> bool:
    if aggregation is None: return True
    if "semantic_role" not in column: return True
    public_name = "average" if aggregation == "mean" else aggregation
    return public_name in column.get("allowed_aggregations", ROLE_AGGREGATIONS.get(column.get("semantic_role", "unknown"), []))


def preferred_automatic_aggregation(column: dict[str, Any]) -> str:
    tokens = set(_normalized(column["name"]).split("_"))
    if tokens & AVERAGE_LIKE: return "mean"
    if tokens & SUM_LIKE: return "sum"
    return "mean"


def validate_semantic_plan(columns: list[dict[str, Any]], plan: Any) -> None:
    by_name = {item["name"]: item for item in columns}
    aggregate_operations = {"aggregate", "group_and_aggregate", "top_n", "bottom_n", "compare_groups", "compare_periods", "percent_of_total", "contribution", "rank", "trend", "running_total", "percentage_change", "moving_average", "compare_segments"}
    effective_aggregation = plan.aggregation or ("sum" if plan.operation in aggregate_operations else None)
    if plan.metric and plan.metric in by_name and not aggregation_allowed(by_name[plan.metric], effective_aggregation):
        role = by_name[plan.metric].get("semantic_role", "unknown")
        raise AppError(f"Aggregation '{effective_aggregation}' is not meaningful for {role} column '{plan.metric}'.", "SEMANTIC_AGGREGATION_INVALID")
    if plan.secondary_metric and plan.secondary_metric in by_name and not aggregation_allowed(by_name[plan.secondary_metric], plan.secondary_aggregation):
        raise AppError(f"The secondary aggregation is not meaningful for '{plan.secondary_metric}'.", "SEMANTIC_AGGREGATION_INVALID")
    if plan.operation in {"contribution", "percent_of_total", "variance", "correlation"} and plan.metric in by_name and by_name[plan.metric].get("semantic_role") != "measure":
        raise AppError(f"Operation '{plan.operation}' requires a semantic measure.", "SEMANTIC_AGGREGATION_INVALID")


def recommend_chart_type(columns: list[dict[str, Any]], plan: Any) -> str:
    by_name = {item["name"]: item for item in columns}
    metric_role = by_name.get(plan.metric, {}).get("semantic_role")
    group_role = by_name.get(plan.group_by[0], {}).get("semantic_role") if plan.group_by else None
    if plan.operation == "trend" or group_role == "temporal_dimension": return "line"
    if plan.operation == "filter" and metric_role == "measure" and plan.group_by and group_role == "measure": return "scatter"
    return "bar"


def describe_chart_plan(plan: Any, question: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Build user-facing chart semantics without changing schema identifiers."""
    dimension = plan.group_by[0] if plan.group_by else ("Period" if plan.operation == "trend" else None)
    aggregation = plan.aggregation or ("count" if plan.operation == "count" else "sum")
    aggregation_labels = {"mean": "Average", "max": "Maximum", "min": "Minimum", "sum": "Total", "median": "Median", "count": "Row count"}
    metric_label = natural_label(plan.metric) if plan.metric else "Value"
    value_label = "Row count" if aggregation == "count" else f"{aggregation_labels.get(aggregation, natural_label(aggregation))} {metric_label.casefold()}"
    effective_limit = limit or plan.limit
    dimension_label = natural_label(dimension or "category")
    if question and dimension:
        question_words = _normalized(question).replace("_", " ")
        dimension_words = _normalized(dimension).replace("_", " ")
        contextual = re.search(rf"\b([a-z0-9]+\s+{re.escape(dimension_words)}s?)\b", question_words)
        if contextual and contextual.group(1).split()[0] not in {"top", "bottom", "the", "by"}:
            dimension_label = contextual.group(1).capitalize()
        elif dimension_words == "name":
            ranked_entity = re.search(r"\b(?:top|bottom)\s+\d+\s+(?:most\s+[a-z0-9]+\s+)?([a-z0-9]+)", question_words)
            if ranked_entity:
                entity = ranked_entity.group(1).removesuffix("s")
                dimension_label = f"{entity.capitalize()} name"
    if plan.operation == "filter" and dimension and plan.metric:
        interpreted_as = f"{natural_label(plan.metric)} vs {dimension_label.casefold()}"
        aggregation = None
        value_label = natural_label(plan.metric)
    elif plan.operation in {"top_n", "bottom_n"}:
        direction = "Top" if plan.operation == "top_n" else "Bottom"
        plural = dimension_label if dimension_label.endswith("s") else f"{dimension_label}s"
        interpreted_as = f"{direction} {effective_limit} most common {plural.casefold()}" if aggregation == "count" else f"{direction} {effective_limit} {plural.casefold()} by {value_label.casefold()}"
    elif dimension:
        interpreted_as = f"{value_label} by {natural_label(dimension).casefold()}"
    else:
        interpreted_as = value_label
    normalized_question = _normalized(question or "")
    metric_mentioned = bool(plan.metric and _normalized(plan.metric).replace("_", " ") in normalized_question.replace("_", " "))
    explicit_intent = any(phrase in normalized_question for phrase in ("most_expensive", "most_common", "best_selling", "most_profitable", "cheapest"))
    inferred = plan.operation in {"top_n", "bottom_n"} and not metric_mentioned and not explicit_intent
    return {
        "interpreted_as": interpreted_as,
        "dimension": dimension,
        "metric": "row_count" if aggregation == "count" else plan.metric,
        "aggregation": "average" if aggregation == "mean" else aggregation,
        "sort": "ascending" if plan.operation == "bottom_n" or plan.sort == "asc" else "descending" if plan.operation == "top_n" or plan.sort == "desc" else None,
        "limit": effective_limit,
        "inferred": inferred,
        "x_axis_label": dimension_label[:-1] if dimension_label.endswith("s") else dimension_label if dimension else None,
        "y_axis_label": value_label,
        "tooltip_label": value_label,
    }
