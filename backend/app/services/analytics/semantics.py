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
ID_TOKENS = {"id", "identifier", "invoice", "transaction", "serial", "registration", "account", "customer", "order"}
ID_SUFFIXES = ("_id", " id", "_number", " number", "_no", " no", "_code")
BOOLEAN_NAMES = {"active", "enabled", "disabled", "flag", "is_active", "is_deleted", "success", "valid"}
SUM_LIKE = {"sales", "revenue", "amount", "profit", "quantity", "qty", "cost", "units", "volume", "total"}
AVERAGE_LIKE = {"price", "rate", "ratio", "percentage", "percent", "margin", "score", "age", "distance", "mileage", "km", "temperature"}


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _physical_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series): return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series): return "datetime"
    if pd.api.types.is_integer_dtype(series): return "integer"
    if pd.api.types.is_numeric_dtype(series): return "number"
    return "string"


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
    boolean_values = {str(value).strip().casefold() for value in clean.unique()[:10]}
    boolean_like = physical == "boolean" or (unique <= 2 and (normalized in BOOLEAN_NAMES or boolean_values <= {"true", "false", "yes", "no", "y", "n", "0", "1"}))

    if boolean_like:
        role: SemanticRole = "boolean_dimension"; confidence = 0.98 if physical == "boolean" else 0.86
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
    return {
        "physical_type": physical, "semantic_role": role, "confidence": round(confidence, 2),
        "allowed_aggregations": ROLE_AGGREGATIONS[role], "uniqueness_ratio": round(ratio, 4),
    }


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
