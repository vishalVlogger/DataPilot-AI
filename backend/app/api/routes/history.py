from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.core.auth import current_principal, require_auth
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.repositories import AnalysisRunRepository, AnalysisSessionRepository, DatasetRepository, JobRepository, SavedAnalysisRepository
from app.schemas.dataset import AnalysisPlan, AnalysisRunResponse, DrillDownRequest, DrillDownResponse, JobResponse, SavedAnalysisRequest, SavedAnalysisResponse, SessionCreateRequest, SessionResponse
from app.services.analytics.engines import ExecutionEngineSelector
from app.services.analytics.profiler import profile_dataset
from app.services.cache import analysis_cache
from app.services.datasets.storage import DatasetStorage
from app.services.saas import UsageService

router = APIRouter(dependencies=[Depends(require_auth)])


def storage() -> DatasetStorage:
    settings = get_settings(); principal = current_principal()
    return DatasetStorage(settings.storage_root, settings.parquet_compression, principal.workspace_id, principal.user_id)


def _public_job(item: dict) -> dict:
    item = dict(item); item["result_reference"] = f"/api/jobs/{item['id']}/result" if item.get("result_reference") else None
    return item


@router.get("/datasets", response_model=list[dict])
async def list_datasets(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), search: str | None = Query(None, max_length=100), source_type: str | None = None, recently_analyzed: bool = False) -> list[dict]:
    principal = current_principal()
    with session_scope() as session: items = DatasetRepository(session, principal.workspace_id).list(limit, offset, search, source_type, recently_analyzed)
    return [{"id": item["id"], "name": item["name"], "source_type": item["source_type"], "rows": item["row_count"], "columns": item["column_count"], "created_at": item["created_at"], "updated_at": item["updated_at"], "current_version": item["current_version"], "storage_format": item["storage_format"], "status": item["status"], "last_analyzed_at": item["last_analyzed_at"], "storage_bytes": item["storage_bytes"]} for item in items]


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str) -> None:
    principal = current_principal(); store = storage(); metadata = store.load_metadata(dataset_id); store.delete_dataset(dataset_id); analysis_cache.invalidate_dataset(dataset_id)
    UsageService(principal.workspace_id).activity("dataset_deleted", principal.user_id, dataset_id, {"name": metadata["name"]})


@router.post("/datasets/{dataset_id}/sessions", response_model=SessionResponse, status_code=201)
async def create_session(dataset_id: str, request: SessionCreateRequest) -> SessionResponse:
    principal = current_principal(); store = storage(); store.load_metadata(dataset_id)
    with session_scope() as session: item = AnalysisSessionRepository(session, principal.workspace_id).create(dataset_id, store.current_version(dataset_id), request.title, principal.user_id)
    UsageService(principal.workspace_id).activity("session_created", principal.user_id, dataset_id, {"session_id": item["id"]})
    return SessionResponse.model_validate(item)


@router.get("/datasets/{dataset_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(dataset_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> list[SessionResponse]:
    principal = current_principal(); storage().load_metadata(dataset_id)
    with session_scope() as session: items = AnalysisSessionRepository(session, principal.workspace_id).list(dataset_id, limit, offset)
    return [SessionResponse.model_validate(item) for item in items]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    principal = current_principal()
    with session_scope() as session: item = AnalysisSessionRepository(session, principal.workspace_id).get(session_id)
    return SessionResponse.model_validate(item)


@router.get("/sessions/{session_id}/runs", response_model=list[AnalysisRunResponse])
async def list_session_runs(session_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> list[AnalysisRunResponse]:
    principal = current_principal()
    with session_scope() as session: items = AnalysisRunRepository(session, principal.workspace_id).list(session_id, limit, offset)
    return [AnalysisRunResponse.model_validate(item) for item in items]


@router.post("/datasets/{dataset_id}/saved-analyses", response_model=SavedAnalysisResponse, status_code=201)
async def save_analysis(dataset_id: str, request: SavedAnalysisRequest) -> SavedAnalysisResponse:
    principal = current_principal(); storage().load_metadata(dataset_id)
    with session_scope() as session: item = SavedAnalysisRepository(session, principal.workspace_id).create(dataset_id, request.name, request.plan.model_dump(mode="json"), request.chart_config, principal.user_id)
    UsageService(principal.workspace_id).activity("analysis_saved", principal.user_id, dataset_id, {"saved_analysis_id": item["id"], "name": request.name})
    return SavedAnalysisResponse.model_validate(item)


@router.get("/datasets/{dataset_id}/saved-analyses", response_model=list[SavedAnalysisResponse])
async def list_saved_analyses(dataset_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> list[SavedAnalysisResponse]:
    principal = current_principal(); storage().load_metadata(dataset_id)
    with session_scope() as session: items = SavedAnalysisRepository(session, principal.workspace_id).list(dataset_id, limit, offset)
    return [SavedAnalysisResponse.model_validate(item) for item in items]


@router.delete("/saved-analyses/{analysis_id}", status_code=204)
async def delete_saved_analysis(analysis_id: str) -> None:
    principal = current_principal()
    with session_scope() as session: SavedAnalysisRepository(session, principal.workspace_id).delete(analysis_id)


@router.post("/saved-analyses/{analysis_id}/run")
async def run_saved_analysis(analysis_id: str) -> dict:
    principal = current_principal(); usage = UsageService(principal.workspace_id); usage.enforce_analysis()
    with session_scope() as session:
        saved = SavedAnalysisRepository(session, principal.workspace_id).get(analysis_id); dataset_id, plan_data, chart_config = saved.dataset_id, saved.query_plan, saved.chart_config
    store = storage(); metadata = store.load_metadata(dataset_id); plan = AnalysisPlan.model_validate(plan_data); engine = ExecutionEngineSelector(get_settings()).select(metadata["rows"]); source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id); result = await engine.execute_plan(source, plan)
    usage.record("analysis", 1, principal.user_id, dataset_id, {"saved_analysis_id": analysis_id}); usage.activity("saved_analysis_run", principal.user_id, dataset_id, {"saved_analysis_id": analysis_id})
    return {"saved_analysis_id": analysis_id, "dataset_id": dataset_id, "plan": plan, "result": result.result, "chart_config": chart_config, "metadata": {"execution_engine": result.engine, "execution_ms": result.duration_ms, "dataset_version": store.current_version(dataset_id)}}


@router.post("/datasets/{dataset_id}/drilldown", response_model=DrillDownResponse)
async def drill_down(dataset_id: str, request: DrillDownRequest) -> DrillDownResponse:
    principal = current_principal(); usage = UsageService(principal.workspace_id); usage.enforce_analysis(); store = storage(); metadata = store.load_metadata(dataset_id); profile = metadata.get("profile_summary") or {}
    if not profile or any("semantic_role" not in item for item in profile.get("columns", [])): profile = profile_dataset(store.load_frame(dataset_id), dataset_id); store.update_profile(dataset_id, profile)
    columns = {item["name"] for item in profile.get("columns", [])}
    if request.clicked_dimension not in columns or request.next_dimension not in columns: raise AppError("The drilldown dimension is not part of this dataset.", "INVALID_QUERY_PLAN")
    from app.schemas.dataset import FilterCondition
    plan = request.base_plan.model_copy(deep=True, update={"operation": "group_and_aggregate"}); plan.filters.append(FilterCondition(column=request.clicked_dimension, operator="equals", value=request.clicked_value)); plan.group_by = [request.next_dimension]
    engine = ExecutionEngineSelector(get_settings()).select(metadata["rows"]); source = store.get_dataset_path(dataset_id) if engine.name == "duckdb" else store.load_frame(dataset_id); result = await engine.execute_plan(source, plan); crumb = [*request.breadcrumb, f"{request.clicked_dimension}: {request.clicked_value}"]
    usage.record("analysis", 1, principal.user_id, dataset_id, {"operation": "drilldown"})
    return DrillDownResponse(plan=plan, result=result.result, breadcrumb=crumb, metadata={"execution_engine": result.engine, "execution_ms": result.duration_ms, "dataset_version": store.current_version(dataset_id)})


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> list[JobResponse]:
    principal = current_principal()
    with session_scope() as session: items = JobRepository(session, principal.workspace_id).list(limit, offset)
    return [JobResponse.model_validate(_public_job(item)) for item in items]


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    principal = current_principal()
    with session_scope() as session: item = JobRepository(session, principal.workspace_id).get(job_id)
    return JobResponse.model_validate(_public_job(item))


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str) -> FileResponse:
    principal = current_principal()
    with session_scope() as session: job = JobRepository(session, principal.workspace_id).get(job_id)
    if job["status"] != "completed" or not job.get("result_reference"): raise AppError("The job result is not ready.", "JOB_NOT_COMPLETE", 409)
    path = Path(job["result_reference"]).resolve(); root = get_settings().storage_root.resolve()
    if root not in path.parents or not path.is_file(): raise AppError("The job result is unavailable.", "JOB_RESULT_NOT_FOUND", 404)
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/html"
    return FileResponse(path, media_type=media_type, filename=path.name)
