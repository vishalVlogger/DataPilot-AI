from typing import Any

import pandas as pd

from app.services.analytics.executor import trend
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.semantics import preferred_automatic_aggregation


def _label(name: str) -> str:
    return name.replace("_", " ")


def _distribution_insights(frame: pd.DataFrame, column: dict[str, Any], max_categories: int) -> list[dict[str, Any]]:
    name = column["name"]; counts = frame[name].dropna().value_counts()
    if len(counts) < 2 or len(counts) > max_categories: return []
    total = int(counts.sum()); most, least = counts.index[0], counts.index[-1]; most_count, least_count = int(counts.iloc[0]), int(counts.iloc[-1])
    share = round(most_count / total * 100, 2) if total else 0.0; label = _label(name)
    return [
        {"type": "performance", "severity": "info", "title": f"{most} is the most common {label}", "description": f"{most} appears in {most_count:,} records and represents {share:.1f}% of non-missing {label} values.", "metric": name, "value": most_count},
        {"type": "distribution", "severity": "info", "title": f"{most} represents {share:.1f}% of {label} values", "description": f"This percentage is based on row counts, not a sum of an unrelated numeric column.", "metric": name, "value": share},
        {"type": "distribution", "severity": "info", "title": f"{least} is the least common {label}", "description": f"{least} appears in {least_count:,} record{'s' if least_count != 1 else ''}.", "metric": name, "value": least_count},
    ]


def _measure_by_category(frame: pd.DataFrame, measure: dict[str, Any], category: dict[str, Any]) -> list[dict[str, Any]]:
    metric, dimension = measure["name"], category["name"]; aggregation = preferred_automatic_aggregation(measure)
    working = frame[[dimension, metric]].copy(); working[metric] = pd.to_numeric(working[metric], errors="coerce"); working = working.dropna()
    if working.empty: return []
    grouped = working.groupby(dimension)[metric].agg(aggregation).sort_values(ascending=False)
    if grouped.empty: return []
    high, low = grouped.index[0], grouped.index[-1]; high_value, low_value = float(grouped.iloc[0]), float(grouped.iloc[-1])
    label = _label(metric); dimension_label = _label(dimension)
    operation = "total" if aggregation == "sum" else "average" if aggregation == "mean" else aggregation
    insights = [
        {"type": "performance", "severity": "info", "title": f"{high} has the highest {operation} {label}", "description": f"Among {dimension_label} groups, {high} has a calculated {operation} {label} of {high_value:,.2f}.", "metric": metric, "value": high_value},
        {"type": "performance", "severity": "info", "title": f"{low} has the lowest {operation} {label}", "description": f"Among {dimension_label} groups, {low} has a calculated {operation} {label} of {low_value:,.2f}.", "metric": metric, "value": low_value},
    ]
    if aggregation == "sum":
        total = float(grouped.sum()); contribution = 0 if total == 0 else round(high_value / total * 100, 2)
        if contribution >= 50:
            insights.append({"type": "concentration", "severity": "warning", "title": f"{label} is concentrated in {high}", "description": f"{high} contributes {contribution:.1f}% of total {label} across {dimension_label} groups.", "metric": metric, "value": contribution})
    return insights


def generate_insights(frame: pd.DataFrame, dataset_id: str, max_categories: int = 100) -> list[dict[str, Any]]:
    profile = profile_dataset(frame, dataset_id); insights: list[dict[str, Any]] = []
    for column in profile["columns"]:
        if column["missing_percentage"] >= 10:
            severity = "critical" if column["missing_percentage"] >= 40 else "warning"
            insights.append({"type": "data_quality", "severity": severity, "title": f"High missing values in {column['name']}", "description": f"{column['missing_count']:,} values are missing ({column['missing_percentage']:.1f}%).", "metric": column["name"], "value": column["missing_percentage"]})
    if profile["duplicate_rows"]:
        insights.append({"type": "data_quality", "severity": "warning", "title": "Duplicate rows detected", "description": f"The dataset contains {profile['duplicate_rows']:,} duplicate rows.", "value": profile["duplicate_rows"]})

    dimensions = [item for item in profile["columns"] if item["semantic_role"] in {"categorical_dimension", "boolean_dimension"} and 1 < item["unique_count"] <= max_categories]
    measures = [item for item in profile["columns"] if item["semantic_role"] == "measure"]
    for dimension in dimensions[:3]: insights.extend(_distribution_insights(frame, dimension, max_categories))
    if measures and dimensions: insights.extend(_measure_by_category(frame, measures[0], dimensions[0]))

    for measure in measures[:5]:
        metric = measure["name"]; series = pd.to_numeric(frame[metric], errors="coerce").dropna()
        if len(series) >= 4:
            q1, q3 = series.quantile([0.25, 0.75]); spread = q3 - q1
            outliers = int(((series < q1 - 1.5 * spread) | (series > q3 + 1.5 * spread)).sum())
            if outliers:
                insights.append({"type": "outlier", "severity": "warning", "title": f"Unusual values in {_label(metric)}", "description": f"{outliers:,} measure values fall outside the standard IQR outlier range.", "metric": metric, "value": outliers})

    if measures and profile["date_columns"]:
        measure, date_column = measures[0], profile["date_columns"][0]; metric = measure["name"]; aggregation = preferred_automatic_aggregation(measure)
        periods = trend(frame, metric, date_column, "month", aggregation)
        if periods:
            high = max(periods, key=lambda row: row[metric]); low = min(periods, key=lambda row: row[metric]); operation = "total" if aggregation == "sum" else "average"
            insights.extend([
                {"type": "trend", "severity": "info", "title": f"{high['Period']} had the highest {operation} {_label(metric)}", "description": f"The calculated value was {high[metric]:,.2f}.", "metric": metric, "value": high[metric]},
                {"type": "trend", "severity": "info", "title": f"{low['Period']} had the lowest {operation} {_label(metric)}", "description": f"The calculated value was {low[metric]:,.2f}.", "metric": metric, "value": low[metric]},
            ])
            changes = [row for row in periods if row.get("change_percentage") is not None]
            if changes:
                growth = max(changes, key=lambda row: row["change_percentage"]); decline = min(changes, key=lambda row: row["change_percentage"])
                if growth["change_percentage"] > 10: insights.append({"type": "growth", "severity": "info", "title": f"Large growth in {growth['Period']}", "description": f"{_label(metric)} increased {growth['change_percentage']:.1f}% from the previous period.", "metric": metric, "value": growth["change_percentage"]})
                if decline["change_percentage"] < -10: insights.append({"type": "decline", "severity": "warning", "title": f"Large decline in {decline['Period']}", "description": f"{_label(metric)} declined {abs(decline['change_percentage']):.1f}% from the previous period.", "metric": metric, "value": decline["change_percentage"]})
    return insights
