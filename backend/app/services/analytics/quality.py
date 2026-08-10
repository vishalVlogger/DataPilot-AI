from collections import defaultdict
from typing import Any

import pandas as pd


def analyze_quality(frame: pd.DataFrame, max_examples: int = 5) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    missing = frame.isna().sum()
    for column, count in missing[missing > 0].items():
        issues.append({"issue_type": "missing_values", "column": str(column), "count": int(count), "examples": [], "severity": "critical" if count / max(len(frame), 1) >= .4 else "warning"})
    duplicates = int(frame.duplicated().sum())
    if duplicates:
        issues.append({"issue_type": "duplicate_rows", "column": None, "count": duplicates, "examples": [], "severity": "warning"})
    for column in frame.select_dtypes(include=["object", "string"]).columns:
        series = frame[column].dropna().astype(str)
        if series.empty:
            continue
        leading = series.str.match(r"^\s+").fillna(False)
        trailing = series.str.match(r".*\s+$").fillna(False)
        empty = series.str.strip().eq("")
        for issue_type, mask in [("leading_whitespace", leading), ("trailing_whitespace", trailing), ("empty_strings", empty)]:
            if mask.any():
                issues.append({"issue_type": issue_type, "column": str(column), "count": int(mask.sum()), "examples": series[mask].head(max_examples).tolist(), "severity": "warning"})
        variants: dict[str, set[str]] = defaultdict(set)
        for item in series.unique()[:1000]:
            variants[item.strip().casefold()].add(item)
        inconsistent = [sorted(values) for values in variants.values() if len(values) > 1]
        if inconsistent:
            examples = [value for group in inconsistent for value in group][:max_examples]
            count = int(series.str.strip().str.casefold().isin([key for key, values in variants.items() if len(values) > 1]).sum())
            issues.append({"issue_type": "suspicious_category_variants", "column": str(column), "count": count, "examples": examples, "severity": "warning"})
        nonempty = series[~empty]
        if len(nonempty) >= 3:
            numeric = pd.to_numeric(nonempty.str.replace(",", "", regex=False), errors="coerce")
            if numeric.notna().mean() >= .6 and numeric.isna().any():
                issues.append({"issue_type": "invalid_numeric_values", "column": str(column), "count": int(numeric.isna().sum()), "examples": nonempty[numeric.isna()].head(max_examples).tolist(), "severity": "warning"})
            if "date" in str(column).lower():
                dates = pd.to_datetime(nonempty, errors="coerce")
                if dates.isna().any():
                    issues.append({"issue_type": "invalid_dates", "column": str(column), "count": int(dates.isna().sum()), "examples": nonempty[dates.isna()].head(max_examples).tolist(), "severity": "warning"})
    return issues
