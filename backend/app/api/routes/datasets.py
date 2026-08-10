from io import BytesIO
from pathlib import Path
import re
import pandas as pd

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.schemas.dataset import (
    AskRequest, AskResponse, ChartRequest, ChartResponse, ChartSuggestion,
    CleaningApplyResponse, CleaningPreview, CleaningRequest, DatasetMetadata,
    DatasetProfile, Insight, InspectResponse, QualityIssue, SheetInfo,
)
from app.services.ai import get_ai_provider
from app.services.analytics.executor import execute_plan
from app.services.analytics.insights import generate_insights
from app.services.analytics.profiler import profile_dataset
from app.services.analytics.quality import analyze_quality
from app.services.cleaning.service import audit_entries, clean_frame
from app.services.datasets.parser import inspect_sheets, parse_dataset
from app.services.datasets.storage import DatasetStorage
from app.services.visualization.charts import generate_chart

router = APIRouter(prefix="/datasets")


def storage() -> DatasetStorage:
    return DatasetStorage(get_settings().data_storage_dir)


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
    return DatasetMetadata.model_validate(storage().save(frame, file.filename or "upload", source_type, selected_sheet))


@router.get("/{dataset_id}", response_model=DatasetMetadata)
async def get_dataset(dataset_id: str) -> DatasetMetadata:
    return DatasetMetadata.model_validate(storage().load_metadata(dataset_id))


@router.get("/{dataset_id}/profile", response_model=DatasetProfile)
async def get_profile(dataset_id: str) -> DatasetProfile:
    return DatasetProfile.model_validate(profile_dataset(storage().load_frame(dataset_id), dataset_id))


@router.post("/{dataset_id}/ask", response_model=AskResponse)
async def ask_dataset(dataset_id: str, request: AskRequest) -> AskResponse:
    settings = get_settings()
    frame = storage().load_frame(dataset_id)
    profile = profile_dataset(frame, dataset_id)
    provider = get_ai_provider(settings)
    plan = await provider.create_analysis_plan(request.question, profile["columns"])
    result = execute_plan(frame, plan)
    answer = await provider.explain_result(request.question, plan, result)
    suggestion = ChartSuggestion(type="line" if plan.operation == "trend" else "bar") if isinstance(result, list) and result else None
    return AskResponse(question=request.question, plan=plan, answer=answer, result=result, chart_suggestion=suggestion)


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
        plan = await get_ai_provider(settings).create_analysis_plan(request.question or "", profile["columns"])
    result = generate_chart(frame, plan, request.chart_type, settings.max_chart_rows)
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
    store.save_working_frame(dataset_id, cleaned)
    audit = store.append_audit(dataset_id, audit_entries(preview))
    return CleaningApplyResponse(preview=preview, audit_entries=audit, profile=DatasetProfile.model_validate(profile_dataset(cleaned, dataset_id)))


@router.post("/{dataset_id}/reset", response_model=DatasetProfile)
async def reset_dataset(dataset_id: str) -> DatasetProfile:
    frame = storage().reset(dataset_id)
    return DatasetProfile.model_validate(profile_dataset(frame, dataset_id))


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
