from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.dataset import ReportRequest
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.quality import analyze_quality


def _footer(canvas, document) -> None:
    canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor("#6c7486")); canvas.drawCentredString(A4[0] / 2, 12 * mm, f"DataPilot AI - Page {document.page}"); canvas.restoreState()


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return escape(str(value))


def generate_pdf_report(frame: pd.DataFrame, dataset_id: str, options: ReportRequest, versions: dict[str, Any]) -> bytes:
    output = BytesIO(); document = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title=options.title)
    styles = getSampleStyleSheet(); styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], textColor=colors.HexColor("#17233f"), alignment=TA_CENTER, spaceAfter=14)); styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#3758f9"), spaceBefore=14, spaceAfter=8))
    story: list[Any] = [Paragraph(escape(options.title), styles["ReportTitle"]), Paragraph("Generated from deterministic calculations over the current dataset version.", styles["BodyText"]), Spacer(1, 8)]
    profile = profile_dataset(frame, dataset_id)
    story.extend([Paragraph("Dataset overview", styles["Section"]), Table([["Rows", f"{profile['row_count']:,}", "Columns", f"{profile['column_count']:,}"], ["Missing", f"{profile['missing_values']:,}", "Duplicates", f"{profile['duplicate_rows']:,}"]], colWidths=[30 * mm, 35 * mm, 30 * mm, 35 * mm], style=[("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7ff")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#d9deea")), ("PADDING", (0, 0), (-1, -1), 7)])])
    if options.include_profile:
        rows = [["Column", "Sum", "Mean", "Median", "Min", "Max"]]
        for item in [column for column in profile["columns"] if column["semantic_role"] == "measure"][:20]: rows.append([_display(item["name"]), *[_display(item.get(key)) for key in ("sum", "mean", "median", "minimum", "maximum")]])
        story.extend([Paragraph("Measure profile", styles["Section"]), Table(rows, repeatRows=1, style=[("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17233f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#ccd2df")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("PADDING", (0, 0), (-1, -1), 4)])])
        semantic_rows = [["Column", "Role", "Confidence", "Allowed aggregations"]] + [[_display(item["name"]), _display(item["semantic_role"].replace("_", " ")), f"{item['confidence']:.0%}", Paragraph(_display(", ".join(item["allowed_aggregations"])), styles["BodyText"])] for item in profile["columns"][:30]]
        story.extend([Paragraph("Semantic column profile", styles["Section"]), Table(semantic_rows, repeatRows=1, colWidths=[38 * mm, 43 * mm, 25 * mm, 60 * mm], style=[("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17233f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#ccd2df")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")])])
    if options.include_insights:
        story.append(Paragraph("Key insights", styles["Section"]))
        for item in generate_insights(frame, dataset_id)[:15]: story.append(KeepTogether([Paragraph(f"<b>{escape(item['title'])}</b>", styles["BodyText"]), Paragraph(escape(item["description"]), styles["BodyText"]), Spacer(1, 5)]))
    if options.include_quality:
        issues = analyze_quality(frame)[:20]
        story.append(Paragraph("Data quality", styles["Section"]))
        if issues:
            rows = [["Issue", "Column", "Count", "Confidence", "Assessment"]] + [[_display(item["issue_type"].replace("_", " ").title()), _display(item.get("column") or "Dataset"), item["count"], item["confidence"].title(), Paragraph(_display(item.get("message") or ""), styles["BodyText"])] for item in issues]
            story.append(Table(rows, repeatRows=1, colWidths=[35 * mm, 30 * mm, 16 * mm, 22 * mm, 63 * mm], style=[("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17233f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#ccd2df")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        else:
            story.append(Paragraph("No data-quality issues were detected by the configured checks.", styles["BodyText"]))
    if options.include_charts: story.extend([Paragraph("Chart summary", styles["Section"]), Paragraph(f"{len(profile['measure_columns'])} semantic measures and {len(profile['dimension_columns'])} trusted dimensions are available for deterministic charts. Interactive chart data remains available in DataPilot AI.", styles["BodyText"])])
    if options.include_version_history:
        rows = [["Version", "Created", "Operation", "Description", "Affected Rows"]] + [[item["version"], str(item["created_at"])[:19], _display(item["operation"]), _display(item["description"]), item["affected_rows"]] for item in versions["versions"][-20:]]
        story.extend([PageBreak(), Paragraph("Version history", styles["Section"]), Table(rows, repeatRows=1, colWidths=[15 * mm, 37 * mm, 25 * mm, 75 * mm, 18 * mm], style=[("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17233f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#ccd2df")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")])])
    try: document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    except Exception as exc:
        from app.core.errors import AppError
        raise AppError("Unable to render the PDF report.", "REPORT_RENDER_FAILED", 500) from exc
    return output.getvalue()
