from io import BytesIO
from pathlib import Path
import re
from time import perf_counter
import logging
from fastapi.encoders import jsonable_encoder
import pandas as pd

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from app.core.config import get_settings
from app.schemas.dataset import (
    AnalyzeRequest, AnalysisResponse, AskRequest, AskResponse, ChartRequest, ChartResponse, ChartSuggestion,
    CleaningApplyResponse, CleaningPreview, CleaningRequest, DatasetMetadata,
    DatasetProfile, Insight, InspectResponse, QualityIssue, ReportRequest, SheetInfo, VersionListResponse,
)
from app.services.ai import get_ai_provider
from app.services.analytics.executor import execute_plan
from app.services.analytics.executor import validate_plan
from app.services.analytics.engines import ExecutionEngineSelector
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.quality import analyze_quality
from app.services.cleaning.service import audit_entries, clean_frame
from app.services.datasets.parser import inspect_sheets, parse_dataset
from app.services.datasets.storage import DatasetStorage
from app.services.ai.mock import MockAIProvider
from app.services.cache import analysis_cache
from app.services.reports import generate_html_report
from app.services.reports import generate_pdf_report
from app.services.jobs import JobManager
from app.core.database import session_scope
from app.repositories import AnalysisRunRepository, AnalysisSessionRepository, DatasetRepository
from app.services.visualization.charts import generate_chart

router = APIRouter(prefix="/datasets")
logger = logging.getLogger("datapilot.analytics")


def _validate_profile_plan(profile: dict, plan) -> None:
    """Validate provider output without materializing the Parquet dataset."""
    from app.core.errors import AppError
    columns = {item["name"]: item for item in profile["columns"]}
    referenced = [plan.metric, plan.secondary_metric, plan.date_column, *(plan.group_by or []), *(plan.partition_by or [])]
    referenced.extend(item.column for item in plan.filters)
    if plan.date_filter:
        referenced.append(plan.date_filter.column)
    missing = sorted({name for name in referenced if name and name not in columns})
    if missing:
        raise AppError(f"Unknown column(s): {', '.join(missing)}.", "INVALID_QUERY_PLAN")


def _record_run(dataset_id: str, requested_session_id: str | None, version: int, question: str | None, plan, result, engine: str, duration_ms: float, explanation: str | None = None) -> tuple[str, str]:
    summary = result[:50] if isinstance(result, list) else result
    with session_scope() as session:
        sessions = AnalysisSessionRepository(session)
        if requested_session_id:
            session_record = sessions.get(requested_session_id)
            if session_record["dataset_id"] != dataset_id:
                from app.core.errors import AppError
                raise AppError("The analysis session belongs to another dataset.", "SESSION_NOT_FOUND", 404)
        else:
            session_record = sessions.create(dataset_id, version, (question or "Analysis session")[:255])
        sessions.touch(session_record["id"], version)
        run = AnalysisRunRepository(session).create(
            session_id=session_record["id"], dataset_id=dataset_id, dataset_version=version,
            question=question, query_plan=plan.model_dump(mode="json"), result_summary=jsonable_encoder(summary),
            execution_engine=engine, execution_duration_ms=duration_ms, ai_provider=get_settings().ai_provider,
            ai_explanation=explanation, success=True,
        )
        DatasetRepository(session).mark_analyzed(dataset_id)
    return session_record["id"], run["id"]


def storage() -> DatasetStorage:
    settings = get_settings()
    return DatasetStorage(settings.storage_root, settings.parquet_compression)


@router.post("/inspect", response_model=InspectResponse)
async def inspect_dataset(file: UploadFile = File(...)) -> InspectResponse:
    settings = get_settings()
    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    sheets = inspect_sheets(file.filename or "upload", content, settings.max_upload_size_mb)
    return InspectResponse(filename=Path(file.filename or "upload").name, sheets=[SheetInfo(name=name) for name in sheets])


@router.post("/upload", response_model=DatasetMetadata, status_code=201)
async def upload_dataset(file: UploadFile = File(...), sheet_name: str | None = Form(default=None), header_row: int = Form(default=0)) -> DatasetMetadata:
    settings = get_settings()
    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    frame, source_type, selected_sheet = parse_dataset(file.filename or "upload", content, settings.max_upload_size_mb, settings.max_rows, settings.max_columns, sheet_name, header_row)
    store = storage()
    metadata = store.save(frame, file.filename or "upload", source_type, selected_sheet, content)
    store.update_profile(metadata["id"], profile_dataset(frame, metadata["id"]))
    return DatasetMetadata.model_validate(metadata)


@router.get("/{dataset_id}", response_model=DatasetMetadata)
async def get_dataset(dataset_id: str) -> DatasetMetadata:
    return DatasetMetadata.model_validate(storage().load_metadata(dataset_id))


@router.get("/{dataset_id}/profile", response_model=DatasetProfile)
async def get_profile(dataset_id: str) -> DatasetProfile:
    store = storage(); metadata = store.load_metadata(dataset_id)
    profile = metadata.get("profile_summary")
    if not profile:
        profile = profile_dataset(store.load_frame(dataset_id), dataset_id); store.update_profile(dataset_id, profile)
    return DatasetProfile.model_validate(profile)


@router.post("/{dataset_id}/ask", response_model=AskResponse)
async def ask_dataset(dataset_id: str, request: AskRequest) -> AskResponse:
    settings = get_settings()
    load_started = perf_counter(); store = storage(); metadata_record = store.load_metadata(dataset_id)
    profile = metadata_record.get("profile_summary")
    if not profile:
        frame_for_profile = store.load_frame(dataset_id); profile = profile_dataset(frame_for_profile, dataset_id); store.update_profile(dataset_id, profile)
    load_ms = round((perf_counter() - load_started) * 1000, 3)
    mock = MockAIProvider()
    ai_started = perf_counter()
    fallback_used = False
    try:
        provider = get_ai_provider(settings)
        plan = await provider.create_analysis_plan(request.question, profile["columns"])
        _validate_profile_plan(profile, plan)
    except Exception:
        if settings.ai_provider == "mock": raise
        fallback_used = True
        provider = mock
        plan = await mock.create_analysis_plan(request.question, profile["columns"])
    interpretation_ms = round((perf_counter() - ai_started) * 1000, 3)
    engine = ExecutionEngineSelector(settings).select(metadata_record["rows"])
    version = store.current_version(dataset_id)
    cache_key = f"{dataset_id}:{version}:query:{plan.model_dump_json()}"
    cached = analysis_cache.get(cache_key)
    source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id)
    engine_result = cached or await engine.execute_plan(source, plan)
    if cached is None: analysis_cache.set(cache_key, engine_result)
    result = engine_result.result
    try:
        answer = await provider.explain_result(request.question, plan, result) if not fallback_used else await mock.explain_result(request.question, plan, result)
    except Exception:
        fallback_used = True
        answer = await mock.explain_result(request.question, plan, result)
    suggestion = ChartSuggestion(type="line" if plan.operation == "trend" else "bar") if isinstance(result, list) and result else None
    explanation = {"metric": plan.metric, "aggregation": plan.aggregation, "grouped_by": plan.group_by, "filters": [item.model_dump() for item in plan.filters], "date_filter": plan.date_filter.model_dump() if plan.date_filter else None}
    session_id, run_id = _record_run(dataset_id, request.session_id, version, request.question, plan, result, engine_result.engine, engine_result.duration_ms, answer)
    metadata = {"execution_engine": engine_result.engine, "dataset_version": version, "load_ms": load_ms, "execution_ms": engine_result.duration_ms, "ai_interpretation_ms": interpretation_ms, "provider_fallback": fallback_used, "cached": cached is not None, "session_id": session_id, "run_id": run_id}
    logger.info("analysis_complete", extra={"dataset_id": dataset_id, **metadata})
    return AskResponse(question=request.question, plan=plan, answer=answer, result=result, chart_suggestion=suggestion, explanation=explanation, metadata=metadata)


@router.post("/{dataset_id}/analyze", response_model=AnalysisResponse)
async def analyze_dataset(dataset_id: str, request: AnalyzeRequest) -> AnalysisResponse:
    settings = get_settings(); store = storage(); metadata = store.load_metadata(dataset_id); engine = ExecutionEngineSelector(settings).select(metadata["rows"]); source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id)
    engine_result = await engine.execute_plan(source, request.plan)
    explanation = {"metric": request.plan.metric, "aggregation": request.plan.aggregation, "grouped_by": request.plan.group_by, "filters": [item.model_dump() for item in request.plan.filters], "date_filter": request.plan.date_filter.model_dump() if request.plan.date_filter else None}
    version = store.current_version(dataset_id)
    session_id, run_id = _record_run(dataset_id, request.session_id, version, request.question, request.plan, engine_result.result, engine_result.engine, engine_result.duration_ms)
    return AnalysisResponse(plan=request.plan, result=engine_result.result, explanation=explanation, metadata={"execution_engine": engine_result.engine, "execution_ms": engine_result.duration_ms, "dataset_version": version, "session_id": session_id, "run_id": run_id})


@router.get("/{dataset_id}/insights", response_model=list[Insight])
async def get_insights(dataset_id: str) -> list[Insight]:
    settings = get_settings()
    results = generate_insights(storage().load_frame(dataset_id), dataset_id, settings.max_category_analysis)
    return [Insight.model_validate(item) for item in results]


@router.post("/{dataset_id}/chart", response_model=ChartResponse)
async def create_chart(dataset_id: str, request: ChartRequest) -> ChartResponse:
    settings = get_settings()
    frame = storage().load_frame(dataset_id)
    if request.plan:
        plan = request.plan
    else:
        profile = profile_dataset(frame, dataset_id)
        try:
            plan = await get_ai_provider(settings).create_analysis_plan(request.question or "", profile["columns"])
            validate_plan(frame, plan)
        except Exception:
            if settings.ai_provider == "mock": raise
            plan = await MockAIProvider().create_analysis_plan(request.question or "", profile["columns"])
    if request.drill_down:
        plan = plan.model_copy(update={"filters": [*plan.filters, request.drill_down]})
    result = generate_chart(frame, plan, request.chart_type, settings.max_chart_rows, request.title, request.x_axis_label, request.y_axis_label, request.show_legend)
    result["interpreted_request"] = request.question or result["interpreted_request"]
    return ChartResponse.model_validate(result)


@router.get("/{dataset_id}/quality", response_model=list[QualityIssue])
async def get_quality(dataset_id: str) -> list[QualityIssue]:
    settings = get_settings()
    return [QualityIssue.model_validate(item) for item in analyze_quality(storage().load_frame(dataset_id), settings.max_quality_examples)]


@router.post("/{dataset_id}/clean/preview", response_model=CleaningPreview)
async def preview_cleaning(dataset_id: str, request: CleaningRequest) -> CleaningPreview:
    _, preview = clean_frame(storage().load_frame(dataset_id), request.operations)
    return preview


@router.post("/{dataset_id}/clean/apply", response_model=CleaningApplyResponse)
async def apply_cleaning(dataset_id: str, request: CleaningRequest) -> CleaningApplyResponse:
    if not request.confirmed:
        from app.core.errors import AppError
        raise AppError("Cleaning changes must be previewed and explicitly confirmed.", "CLEANING_APPLY_FAILED")
    store = storage()
    cleaned, preview = clean_frame(store.load_frame(dataset_id), request.operations)
    description = "; ".join(f"{item.type}{f' on {item.column}' if item.column else ''}" for item in request.operations)
    version = store.create_version(dataset_id, cleaned, "clean", description, preview.affected_rows)
    audit = store.append_audit(dataset_id, audit_entries(preview))
    analysis_cache.invalidate_dataset(dataset_id)
    profile = profile_dataset(cleaned, dataset_id); store.update_profile(dataset_id, profile)
    return CleaningApplyResponse(preview=preview, audit_entries=audit, profile=DatasetProfile.model_validate(profile), version=version)


@router.post("/{dataset_id}/reset", response_model=DatasetProfile)
async def reset_dataset(dataset_id: str) -> DatasetProfile:
    store = storage(); frame = store.reset(dataset_id); profile = profile_dataset(frame, dataset_id); store.update_profile(dataset_id, profile)
    analysis_cache.invalidate_dataset(dataset_id)
    return DatasetProfile.model_validate(profile)


@router.get("/{dataset_id}/versions", response_model=VersionListResponse)
async def get_versions(dataset_id: str) -> VersionListResponse:
    return VersionListResponse.model_validate(storage().list_versions(dataset_id))


@router.post("/{dataset_id}/versions/{version}/restore", response_model=CleaningApplyResponse)
async def restore_version(dataset_id: str, version: int) -> CleaningApplyResponse:
    store = storage(); frame, new_version = store.restore_version(dataset_id, version); analysis_cache.invalidate_dataset(dataset_id)
    from app.schemas.dataset import CleaningPreview
    preview = CleaningPreview(changes=[], affected_rows=0, affected_cells=0, resulting_rows=len(frame), warnings=[f"Restored version {version} as new version {new_version}."])
    profile = profile_dataset(frame, dataset_id); store.update_profile(dataset_id, profile)
    return CleaningApplyResponse(preview=preview, audit_entries=store.load_audit(dataset_id), profile=DatasetProfile.model_validate(profile), version=new_version)


@router.post("/{dataset_id}/report")
async def create_report(dataset_id: str, request: ReportRequest) -> Response:
    settings = get_settings(); store = storage(); store.load_metadata(dataset_id)
    if request.async_job and settings.background_jobs_enabled:
        job = JobManager().create_report_job(dataset_id, request, store)
        return JSONResponse(content={"job_id": job["id"], "status": job["status"]}, status_code=202)
    frame = store.load_frame(dataset_id)
    if request.format == "pdf":
        if not settings.enable_pdf_reports:
            from app.core.errors import AppError
            raise AppError("PDF reports are disabled.", "REPORT_FORMAT_DISABLED", 400)
        content = generate_pdf_report(frame, dataset_id, request, store.list_versions(dataset_id))
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", request.title).strip("_") or "DataPilot_Report"
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{safe_name}.pdf"'})
    html, duration_ms = generate_html_report(frame, dataset_id, request, store.list_versions(dataset_id))
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", request.title).strip("_") or "DataPilot_Report"
    logger.info("report_generated", extra={"dataset_id": dataset_id, "report_generation_ms": duration_ms})
    return HTMLResponse(html, headers={"Content-Disposition": f'inline; filename="{safe_name}.html"', "X-Report-Generation-Ms": str(duration_ms)})


@router.get("/{dataset_id}/export")
async def export_dataset(
    dataset_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    version: str = Query(default="current", pattern="^(current|original)$"),
) -> StreamingResponse:
    store = storage()
    frame = store.load_original_frame(dataset_id) if version == "original" else store.load_frame(dataset_id)
    metadata = store.load_metadata(dataset_id)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(metadata["name"]).stem).strip("_") or "dataset"
    if format == "csv":
        content = frame.to_csv(index=False).encode("utf-8-sig")
        return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{stem}_{version}.csv"'})
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Data", index=False)
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{stem}_{version}.xlsx"'})
