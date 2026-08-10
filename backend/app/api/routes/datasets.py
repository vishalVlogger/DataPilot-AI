from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from app.core.config import get_settings
from app.schemas.dataset import AskRequest, AskResponse, DatasetMetadata, DatasetProfile, InspectResponse, SheetInfo
from app.services.ai import get_ai_provider
from app.services.analytics.executor import execute_plan
from app.services.analytics.profiler import profile_dataset
from app.services.datasets.parser import inspect_sheets, parse_dataset
from app.services.datasets.storage import DatasetStorage

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
    return AskResponse(question=request.question, plan=plan, answer=answer, result=result)
