from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.repositories import AnalysisRunRepository, AnalysisSessionRepository, JobRepository, SavedAnalysisRepository
from app.schemas.dataset import (
    AnalysisPlan,
    AnalysisRunResponse,
    DrillDownRequest,
    DrillDownResponse,
    JobResponse,
    SavedAnalysisRequest,
    SavedAnalysisResponse,
    SessionCreateRequest,
    SessionResponse,
)
from app.services.analytics.engines import ExecutionEngineSelector
from app.services.cache import analysis_cache
from app.services.datasets.storage import DatasetStorage

router = APIRouter()


def storage() -> DatasetStorage:
    settings = get_settings()
    return DatasetStorage(settings.storage_root, settings.parquet_compression)


def _public_job(item: dict) -> dict:
    item = dict(item)
    item["result_reference"] = f"/api/jobs/{item['id']}/result" if item.get("result_reference") else None
    return item


@router.get("/datasets", response_model=list[dict])
async def list_datasets() -> list[dict]:
    return [
        {
            "id": item["id"], "name": item["name"], "source_type": item["source_type"],
            "rows": item["row_count"], "columns": item["column_count"], "created_at": item["created_at"],
            "updated_at": item["updated_at"], "current_version": item["current_version"],
            "storage_format": item["storage_format"], "status": item["status"],
            "last_analyzed_at": item["last_analyzed_at"],
        }
        for item in storage().list_datasets()
    ]


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str) -> None:
    storage().delete_dataset(dataset_id)
    analysis_cache.invalidate_dataset(dataset_id)


@router.post("/datasets/{dataset_id}/sessions", response_model=SessionResponse, status_code=201)
async def create_session(dataset_id: str, request: SessionCreateRequest) -> SessionResponse:
    store = storage(); store.load_metadata(dataset_id)
    with session_scope() as session:
        item = AnalysisSessionRepository(session).create(dataset_id, store.current_version(dataset_id), request.title)
    return SessionResponse.model_validate(item)


@router.get("/datasets/{dataset_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(dataset_id: str) -> list[SessionResponse]:
    storage().load_metadata(dataset_id)
    with session_scope() as session:
        items = AnalysisSessionRepository(session).list(dataset_id)
    return [SessionResponse.model_validate(item) for item in items]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    with session_scope() as session:
        return SessionResponse.model_validate(AnalysisSessionRepository(session).get(session_id))


@router.get("/sessions/{session_id}/runs", response_model=list[AnalysisRunResponse])
async def list_session_runs(session_id: str) -> list[AnalysisRunResponse]:
    with session_scope() as session:
        AnalysisSessionRepository(session).get(session_id)
        items = AnalysisRunRepository(session).list(session_id)
    return [AnalysisRunResponse.model_validate(item) for item in items]


@router.post("/datasets/{dataset_id}/saved-analyses", response_model=SavedAnalysisResponse, status_code=201)
async def save_analysis(dataset_id: str, request: SavedAnalysisRequest) -> SavedAnalysisResponse:
    storage().load_metadata(dataset_id)
    with session_scope() as session:
        item = SavedAnalysisRepository(session).create(dataset_id, request.name, request.plan.model_dump(mode="json"), request.chart_config)
    return SavedAnalysisResponse.model_validate(item)


@router.get("/datasets/{dataset_id}/saved-analyses", response_model=list[SavedAnalysisResponse])
async def list_saved_analyses(dataset_id: str) -> list[SavedAnalysisResponse]:
    storage().load_metadata(dataset_id)
    with session_scope() as session:
        items = SavedAnalysisRepository(session).list(dataset_id)
    return [SavedAnalysisResponse.model_validate(item) for item in items]


@router.delete("/saved-analyses/{analysis_id}", status_code=204)
async def delete_saved_analysis(analysis_id: str) -> None:
    with session_scope() as session:
        SavedAnalysisRepository(session).delete(analysis_id)


@router.post("/saved-analyses/{analysis_id}/run")
async def run_saved_analysis(analysis_id: str) -> dict:
    with session_scope() as session:
        saved = SavedAnalysisRepository(session).get(analysis_id)
        dataset_id, plan_data, chart_config = saved.dataset_id, saved.query_plan, saved.chart_config
    store = storage(); metadata = store.load_metadata(dataset_id); plan = AnalysisPlan.model_validate(plan_data)
    engine = ExecutionEngineSelector(get_settings()).select(metadata["rows"])
    source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id)
    result = await engine.execute_plan(source, plan)
    return {"saved_analysis_id": analysis_id, "dataset_id": dataset_id, "plan": plan, "result": result.result, "chart_config": chart_config, "metadata": {"execution_engine": result.engine, "execution_ms": result.duration_ms, "dataset_version": store.current_version(dataset_id)}}


@router.post("/datasets/{dataset_id}/drilldown", response_model=DrillDownResponse)
async def drill_down(dataset_id: str, request: DrillDownRequest) -> DrillDownResponse:
    store = storage(); metadata = store.load_metadata(dataset_id); profile = metadata.get("profile_summary") or {}
    columns = {item["name"] for item in profile.get("columns", [])}
    if request.clicked_dimension not in columns or request.next_dimension not in columns:
        raise AppError("The drilldown dimension is not part of this dataset.", "INVALID_QUERY_PLAN")
    from app.schemas.dataset import FilterCondition
    plan = request.base_plan.model_copy(deep=True, update={"operation": "group_and_aggregate"})
    plan.filters.append(FilterCondition(column=request.clicked_dimension, operator="equals", value=request.clicked_value))
    plan.group_by = [request.next_dimension]
    engine = ExecutionEngineSelector(get_settings()).select(metadata["rows"])
    source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id)
    result = await engine.execute_plan(source, plan)
    crumb = [*request.breadcrumb, f"{request.clicked_dimension}: {request.clicked_value}"]
    return DrillDownResponse(plan=plan, result=result.result, breadcrumb=crumb, metadata={"execution_engine": result.engine, "execution_ms": result.duration_ms, "dataset_version": store.current_version(dataset_id)})


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    with session_scope() as session:
        return JobResponse.model_validate(_public_job(JobRepository(session).get(job_id)))


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str) -> FileResponse:
    with session_scope() as session:
        job = JobRepository(session).get(job_id)
    if job["status"] != "completed" or not job.get("result_reference"):
        raise AppError("The job result is not ready.", "JOB_NOT_COMPLETE", 409)
    path = Path(job["result_reference"]).resolve(); root = get_settings().storage_root.resolve()
    if root not in path.parents or not path.is_file():
        raise AppError("The job result is unavailable.", "JOB_RESULT_NOT_FOUND", 404)
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/html"
    return FileResponse(path, media_type=media_type, filename=path.name)
