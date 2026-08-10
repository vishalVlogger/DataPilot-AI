from typing import Any

import pandas as pd

from app.services.analytics.executor import trend
from app.services.analytics.profiler import profile_dataset


def generate_insights(frame: pd.DataFrame, dataset_id: str, max_categories: int = 100) -> list[dict[str, Any]]:
    profile = profile_dataset(frame, dataset_id)
    insights: list[dict[str, Any]] = []
    for column in profile["columns"]:
        if column["missing_percentage"] >= 10:
            severity = "critical" if column["missing_percentage"] >= 40 else "warning"
            insights.append({"type": "data_quality", "severity": severity, "title": f"High missing values in {column['name']}", "description": f"{column['missing_count']:,} values are missing ({column['missing_percentage']:.1f}%).", "metric": column["name"], "value": column["missing_percentage"]})
    if profile["duplicate_rows"]:
        insights.append({"type": "data_quality", "severity": "warning", "title": "Duplicate rows detected", "description": f"The dataset contains {profile['duplicate_rows']:,} duplicate rows.", "value": profile["duplicate_rows"]})
    numeric = profile["numeric_columns"]
    categorical = [column for column in profile["categorical_columns"] if 1 < frame[column].nunique(dropna=True) <= max_categories]
    if numeric and categorical:
        metric, category = numeric[0], categorical[0]
        working = frame[[category, metric]].copy()
        working[metric] = pd.to_numeric(working[metric], errors="coerce")
        grouped = working.dropna().groupby(category)[metric].sum().sort_values(ascending=False)
        if not grouped.empty:
            total = float(grouped.sum())
            strongest, weakest = grouped.index[0], grouped.index[-1]
            strongest_value, weakest_value = float(grouped.iloc[0]), float(grouped.iloc[-1])
            contribution = 0.0 if total == 0 else round(strongest_value / total * 100, 2)
            insights.extend([
                {"type": "performance", "severity": "info", "title": f"{strongest} is the strongest {category}", "description": f"{strongest} generated {contribution:.1f}% of total {metric}.", "metric": metric, "value": contribution},
                {"type": "performance", "severity": "info", "title": f"{weakest} is the weakest {category}", "description": f"{weakest} generated {weakest_value:,.2f} in {metric}.", "metric": metric, "value": weakest_value},
            ])
            if contribution >= 50:
                insights.append({"type": "concentration", "severity": "warning", "title": f"{metric} is concentrated in {strongest}", "description": f"One {category} contributes {contribution:.1f}% of total {metric}.", "metric": metric, "value": contribution})
    for metric in numeric[:5]:
        series = pd.to_numeric(frame[metric], errors="coerce").dropna()
        if len(series) >= 4:
            q1, q3 = series.quantile([0.25, 0.75])
            spread = q3 - q1
            outliers = int(((series < q1 - 1.5 * spread) | (series > q3 + 1.5 * spread)).sum())
            if outliers:
                insights.append({"type": "outlier", "severity": "warning", "title": f"Unusual values in {metric}", "description": f"{outliers:,} values fall outside the standard IQR outlier range.", "metric": metric, "value": outliers})
    if numeric and profile["date_columns"]:
        metric, date_column = numeric[0], profile["date_columns"][0]
        periods = trend(frame, metric, date_column, "month", "sum")
        if periods:
            strongest = max(periods, key=lambda row: row[metric])
            weakest = min(periods, key=lambda row: row[metric])
            insights.extend([
                {"type": "trend", "severity": "info", "title": f"{strongest['Period']} was the strongest period", "description": f"It generated {strongest[metric]:,.2f} in {metric}.", "metric": metric, "value": strongest[metric]},
                {"type": "trend", "severity": "info", "title": f"{weakest['Period']} was the weakest period", "description": f"It generated {weakest[metric]:,.2f} in {metric}.", "metric": metric, "value": weakest[metric]},
            ])
            changes = [row for row in periods if row.get("change_percentage") is not None]
            if changes:
                growth = max(changes, key=lambda row: row["change_percentage"])
                decline = min(changes, key=lambda row: row["change_percentage"])
                if growth["change_percentage"] > 10:
                    insights.append({"type": "growth", "severity": "info", "title": f"Large growth in {growth['Period']}", "description": f"{metric} increased {growth['change_percentage']:.1f}% from the previous period.", "metric": metric, "value": growth["change_percentage"]})
                if decline["change_percentage"] < -10:
                    insights.append({"type": "decline", "severity": "warning", "title": f"Large decline in {decline['Period']}", "description": f"{metric} declined {abs(decline['change_percentage']):.1f}% from the previous period.", "metric": metric, "value": decline["change_percentage"]})
    return insights
