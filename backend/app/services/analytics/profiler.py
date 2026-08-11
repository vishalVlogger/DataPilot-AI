from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.services.analytics.semantics import classify_column


def _scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def profile_dataset(frame: pd.DataFrame, dataset_id: str) -> dict[str, Any]:
    settings = get_settings()
    row_count = len(frame)
    numeric = list(frame.select_dtypes(include="number").columns.astype(str))
    booleans = list(frame.select_dtypes(include="bool").columns.astype(str))
    dates: list[str] = []
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            dates.append(str(column))
        elif frame[column].dtype == "object" and frame[column].notna().any():
            parsed = pd.to_datetime(frame[column], errors="coerce", format="mixed")
            # Keep mostly-date columns classified as dates; malformed values remain
            # visible to the later data-quality workflow instead of hiding the type.
            if parsed.notna().mean() >= 0.6 and parsed.notna().sum() >= 2:
                dates.append(str(column))
    categorical = [str(c) for c in frame.columns if str(c) not in numeric + dates + booleans]
    columns: list[dict[str, Any]] = []
    for column in frame.columns:
        name = str(column)
        series = frame[column]
        missing = int(series.isna().sum())
        item: dict[str, Any] = {
            "name": name,
            "data_type": str(series.dtype),
            "category": "numeric" if name in numeric else "date" if name in dates else "boolean" if name in booleans else "categorical",
            "missing_count": missing,
            "missing_percentage": round((missing / row_count * 100) if row_count else 0, 2),
            "unique_count": int(series.nunique(dropna=True)),
            **classify_column(
                name, series, year_min=settings.semantic_year_min,
                year_tolerance=settings.semantic_year_tolerance,
                high_cardinality_min_unique=settings.high_cardinality_min_unique,
                high_cardinality_ratio=settings.high_cardinality_ratio,
            ),
        }
        if name in dates:
            item.update(semantic_role="temporal_dimension", confidence=0.96, allowed_aggregations=["min", "max", "count", "distinct_count"])
        if item["category"] == "categorical":
            item["sample_values"] = [str(value) for value in series.dropna().unique()[:20]]
        clean = series.dropna()
        if name in numeric and not clean.empty:
            item.update(minimum=_scalar(clean.min()), maximum=_scalar(clean.max()), mean=_scalar(clean.mean()), median=_scalar(clean.median()), sum=_scalar(clean.sum()), standard_deviation=_scalar(clean.std(ddof=1)))
        elif name in dates and not clean.empty:
            parsed = pd.to_datetime(clean, errors="coerce", format="mixed").dropna()
            if not parsed.empty:
                item.update(minimum=parsed.min().isoformat(), maximum=parsed.max().isoformat())
        columns.append(item)
    all_dates = [pd.to_datetime(frame[c], errors="coerce", format="mixed") for c in dates]
    valid_dates = pd.concat(all_dates).dropna() if all_dates else pd.Series(dtype="datetime64[ns]")
    measures = [item["name"] for item in columns if item["semantic_role"] == "measure"]
    dimensions = [item["name"] for item in columns if item["semantic_role"] in {"categorical_dimension", "temporal_dimension", "boolean_dimension"}]
    return {
        "dataset_id": dataset_id,
        "row_count": row_count,
        "column_count": len(frame.columns),
        "columns": columns,
        "numeric_columns": numeric,
        "categorical_columns": categorical,
        "date_columns": dates,
        "measure_columns": measures,
        "dimension_columns": dimensions,
        "missing_values": int(frame.isna().sum().sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
        "date_range": {"minimum": valid_dates.min().isoformat(), "maximum": valid_dates.max().isoformat()} if not valid_dates.empty else None,
    }
