from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.errors import AppError
from app.schemas.dataset import CleaningChange, CleaningOperation, CleaningPreview


def _validate(frame: pd.DataFrame, operation: CleaningOperation) -> None:
    column_optional = {"remove_duplicates", "remove_missing_rows"}
    if operation.type not in column_optional and not operation.column:
        raise AppError("This cleaning operation requires a column.", "CLEANING_PREVIEW_FAILED")
    if operation.column and operation.column not in frame.columns:
        raise AppError(f"Column '{operation.column}' was not found.", "COLUMN_NOT_FOUND")
    if operation.type == "fill_missing_value" and operation.value is None:
        raise AppError("A fill value is required.", "CLEANING_PREVIEW_FAILED")
    if operation.type in {"fill_missing_mean", "fill_missing_median"} and operation.column and not pd.api.types.is_numeric_dtype(frame[operation.column]):
        raise AppError("Mean and median fills require a numeric column.", "CLEANING_PREVIEW_FAILED")


def clean_frame(frame: pd.DataFrame, operations: list[CleaningOperation]) -> tuple[pd.DataFrame, CleaningPreview]:
    working = frame.copy()
    changes: list[CleaningChange] = []
    all_rows: set[Any] = set()
    total_cells = 0
    for operation in operations:
        _validate(working, operation)
        before_examples: list[str] = []
        after_examples: list[str] = []
        warnings: list[str] = []
        if operation.type == "remove_duplicates":
            mask = working.duplicated()
            indexes = set(working.index[mask])
            before_examples = [str(item) for item in working.loc[mask].head(3).to_dict(orient="records")]
            working = working.loc[~mask].copy()
            affected_cells = len(indexes) * len(frame.columns)
        elif operation.type == "remove_missing_rows":
            subset = [operation.column] if operation.column else None
            mask = working[subset].isna().any(axis=1) if subset else working.isna().any(axis=1)
            indexes = set(working.index[mask])
            before_examples = [str(item) for item in working.loc[mask].head(3).to_dict(orient="records")]
            affected_cells = int(working.loc[mask].isna().sum().sum())
            working = working.loc[~mask].copy()
        else:
            column = operation.column
            series = working[column]
            if operation.type == "trim_whitespace":
                transformed = series.map(lambda item: item.strip() if isinstance(item, str) else item)
            elif operation.type == "standardize_lowercase":
                transformed = series.map(lambda item: item.lower() if isinstance(item, str) else item)
            elif operation.type == "standardize_uppercase":
                transformed = series.map(lambda item: item.upper() if isinstance(item, str) else item)
            elif operation.type == "standardize_titlecase":
                transformed = series.map(lambda item: item.title() if isinstance(item, str) else item)
            else:
                mask = series.isna()
                fill_value = operation.value
                if operation.type == "fill_missing_mean": fill_value = series.mean()
                if operation.type == "fill_missing_median": fill_value = series.median()
                transformed = series.fillna(fill_value)
            changed = ~(series.eq(transformed) | (series.isna() & transformed.isna()))
            indexes = set(working.index[changed])
            before_examples = [str(item) for item in series[changed].head(5).tolist()]
            after_examples = [str(item) for item in transformed[changed].head(5).tolist()]
            working[column] = transformed
            affected_cells = len(indexes)
        all_rows.update(indexes)
        total_cells += affected_cells
        changes.append(CleaningChange(operation=operation, affected_rows=len(indexes), affected_cells=affected_cells, before_examples=before_examples, after_examples=after_examples, warnings=warnings))
    preview = CleaningPreview(changes=changes, affected_rows=len(all_rows), affected_cells=total_cells, resulting_rows=len(working), warnings=[])
    return working, preview


def audit_entries(preview: CleaningPreview) -> list[dict[str, Any]]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return [{"operation": change.operation.type, "target_column": change.operation.column, "affected_row_count": change.affected_rows, "timestamp": timestamp} for change in preview.changes]
