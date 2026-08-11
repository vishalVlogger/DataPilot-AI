from datetime import datetime, timezone
from html import escape
from time import perf_counter
from typing import Any

import pandas as pd

from app.schemas.dataset import ReportRequest
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.quality import analyze_quality


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(str(item))}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(value if value is not None else '—'))}</td>" for value in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def generate_html_report(frame: pd.DataFrame, dataset_id: str, options: ReportRequest, versions: dict[str, Any]) -> tuple[str, float]:
    started = perf_counter()
    profile = profile_dataset(frame, dataset_id)
    sections = [f"<section><h2>Dataset overview</h2><div class='metrics'><b>{profile['row_count']:,}</b> rows · <b>{profile['column_count']:,}</b> columns · <b>{profile['missing_values']:,}</b> missing values · <b>{profile['duplicate_rows']:,}</b> duplicates</div></section>"]
    if options.include_profile:
        semantic_rows = [[item["name"], item["physical_type"], item["semantic_role"].replace("_", " "), f"{item['confidence']:.0%}", ", ".join(item["allowed_aggregations"])] for item in profile["columns"]]
        measure_rows = [[item["name"], item.get("sum"), item.get("mean"), item.get("median"), item.get("minimum"), item.get("maximum")] for item in profile["columns"] if item["semantic_role"] == "measure"]
        sections.append("<section><h2>Semantic column profile</h2>" + _table(["Column", "Physical type", "Semantic role", "Confidence", "Allowed aggregations"], semantic_rows) + "</section>")
        sections.append("<section><h2>Measure summary</h2>" + (_table(["Measure", "Sum", "Mean", "Median", "Min", "Max"], measure_rows) if measure_rows else "<p>No semantic measures were detected.</p>") + "</section>")
    if options.include_insights:
        insights = generate_insights(frame, dataset_id)
        sections.append("<section><h2>Key insights</h2>" + ("".join(f"<article><h3>{escape(item['title'])}</h3><p>{escape(item['description'])}</p></article>" for item in insights) if insights else "<p>No notable insights were detected.</p>") + "</section>")
    if options.include_quality:
        quality = analyze_quality(frame)
        rows = [[item["issue_type"].replace("_", " ").title(), item.get("column") or "Dataset", item["count"], item["confidence"].title(), item.get("message") or "", ", ".join(item["examples"])] for item in quality]
        sections.append("<section><h2>Data quality</h2>" + (_table(["Issue", "Column", "Count", "Confidence", "Assessment", "Examples"], rows) if rows else "<p>No quality issues were detected.</p>") + "</section>")
    if options.include_charts:
        sections.append(f"<section><h2>Chart data summary</h2><p>{len(profile['measure_columns'])} semantic measures and {len(profile['dimension_columns'])} trusted dimensions are available for deterministic chart generation in DataPilot.</p></section>")
    if options.include_version_history:
        rows = [[item["version"], item["created_at"], item["operation"], item["description"], item["affected_rows"]] for item in versions["versions"]]
        sections.append("<section><h2>Version history</h2>" + _table(["Version", "Created", "Operation", "Description", "Affected rows"], rows) + "</section>")
    generated = datetime.now(timezone.utc).isoformat()
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>{escape(options.title)}</title><style>body{{font:14px Arial,sans-serif;color:#172033;max-width:1000px;margin:40px auto;padding:0 24px}}h1{{color:#17233f}}section{{margin:28px 0}}table{{border-collapse:collapse;width:100%}}th,td{{padding:9px;border:1px solid #dde1e9;text-align:left}}th{{background:#f4f6fa}}article{{border-left:3px solid #3758f9;padding:2px 14px;margin:12px 0}}.meta{{color:#687184}}.metrics{{background:#f4f7ff;padding:18px;border-radius:8px}}</style></head><body><h1>{escape(options.title)}</h1><p class='meta'>Generated {escape(generated)} from deterministic dataset calculations.</p>{''.join(sections)}</body></html>"""
    return html, round((perf_counter() - started) * 1000, 3)
