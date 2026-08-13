from datetime import datetime, timezone
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.auth import Principal, require_auth, require_system_admin
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import AnalysisFeedback, AnalysisRun, BetaUserNote, Dataset, User
from app.services.admin_metrics import audit_admin
from app.services.analytics.profiler import profile_dataset
from app.services.datasets.storage import get_dataset_storage
from app.services.product_analytics import ProductAnalyticsService, ProductEvents, onboarding_state, record_product_event

router = APIRouter(tags=["product-analytics"])


class AnalysisFeedbackRequest(BaseModel):
    helpful: bool
    comment: str | None = Field(default=None, max_length=1000)


class BetaStatusRequest(BaseModel):
    status: Literal["onboarding", "activated", "engaged", "needs_follow_up", "churn_risk", "paused"]


class BetaNoteRequest(BaseModel):
    note: str = Field(min_length=2, max_length=4000)


def _store(principal: Principal):
    settings = get_settings()
    return get_dataset_storage(settings.storage_root, settings.parquet_compression, principal.workspace_id, principal.user_id)


@router.get("/onboarding")
async def get_onboarding(principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        return onboarding_state(session, session.get(User, principal.user_id), principal.workspace_id)


@router.post("/onboarding/dismiss")
async def dismiss_onboarding(principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        user = session.get(User, principal.user_id); user.onboarding_dismissed_at = datetime.now(timezone.utc); session.commit()
    record_product_event(ProductEvents.ONBOARDING_DISMISSED, principal.user_id, principal.workspace_id)
    return {"dismissed": True}


@router.post("/onboarding/sample-dataset", status_code=201)
async def load_sample_dataset(principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        existing = session.scalar(select(Dataset).where(Dataset.workspace_id == principal.workspace_id, Dataset.is_sample.is_(True)).order_by(Dataset.created_at.desc()))
        if existing:
            return _store(principal).load_metadata(existing.id)
    frame = pd.DataFrame([
        {"Date": "2026-01-01", "Region": "North", "Product": "Starter", "Revenue": 4200, "Units": 21},
        {"Date": "2026-01-08", "Region": "South", "Product": "Starter", "Revenue": 3600, "Units": 18},
        {"Date": "2026-02-01", "Region": "North", "Product": "Pro", "Revenue": 6700, "Units": 20},
        {"Date": "2026-02-08", "Region": "West", "Product": "Starter", "Revenue": 2800, "Units": 16},
        {"Date": "2026-03-01", "Region": "South", "Product": "Pro", "Revenue": 7100, "Units": 22},
        {"Date": "2026-03-08", "Region": "West", "Product": "Pro", "Revenue": 5900, "Units": 19},
    ])
    store = _store(principal); metadata = store.save(frame, "DataPilot Sample Sales.csv", "sample", None)
    profile = profile_dataset(frame, metadata["id"]); store.update_profile(metadata["id"], profile)
    with session_scope() as session:
        dataset = session.get(Dataset, metadata["id"]); dataset.is_sample = True; session.commit()
    metadata["is_sample"] = True; metadata["profile_summary"] = profile
    record_product_event(ProductEvents.SAMPLE_LOADED, principal.user_id, principal.workspace_id, "dataset", metadata["id"], {"is_sample": True, "source_type": "sample", "rows_bucket": "under_100"})
    return metadata


@router.get("/onboarding/question-examples")
async def question_examples(dataset_id: str = Query(...), principal: Principal = Depends(require_auth)) -> dict:
    metadata = _store(principal).load_metadata(dataset_id); profile = metadata.get("profile_summary") or {}
    columns = profile.get("columns", []); measure = next((item["name"] for item in columns if item.get("semantic_role") == "measure"), None)
    dimension = next((item["name"] for item in columns if item.get("semantic_role") in {"categorical_dimension", "high_cardinality_dimension", "boolean_dimension"}), None)
    date = next((item["name"] for item in columns if item.get("semantic_role") == "temporal_dimension"), None)
    examples = []
    if measure and dimension: examples += [f"Show total {measure} by {dimension}", f"What are the top 5 {dimension} by {measure}?"]
    if measure and date: examples.append(f"Show the trend of {measure} over {date}")
    if not examples: examples = ["How many rows are in this dataset?", "Summarize the main categories", "Show the most important patterns"]
    return {"examples": examples[:3]}


@router.put("/analysis-runs/{run_id}/feedback")
async def rate_analysis(run_id: str, payload: AnalysisFeedbackRequest, principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.workspace_id == principal.workspace_id, AnalysisRun.user_id == principal.user_id))
        if not run: raise AppError("Analysis result not found.", "ANALYSIS_RUN_NOT_FOUND", 404)
        item = session.scalar(select(AnalysisFeedback).where(AnalysisFeedback.analysis_run_id == run_id, AnalysisFeedback.user_id == principal.user_id))
        if item is None:
            item = AnalysisFeedback(analysis_run_id=run_id, workspace_id=principal.workspace_id, user_id=principal.user_id, helpful=payload.helpful, comment=payload.comment); session.add(item)
        else:
            item.helpful = payload.helpful; item.comment = payload.comment; item.updated_at = datetime.now(timezone.utc)
        session.commit(); response = {"id": item.id, "analysis_run_id": run_id, "helpful": item.helpful, "comment": item.comment}
    record_product_event(ProductEvents.RESULT_RATED, principal.user_id, principal.workspace_id, "analysis_run", run_id, {"helpful": payload.helpful})
    return response


@router.get("/admin/product")
async def product_dashboard(range: str = Query("30", pattern="^(7|30|all)$"), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return ProductAnalyticsService(session).dashboard(None if range == "all" else int(range))


@router.patch("/admin/product/users/{user_id}/status")
async def set_beta_status(user_id: str, payload: BetaStatusRequest, request: Request, admin=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user: raise AppError("User not found.", "USER_NOT_FOUND", 404)
        previous = user.beta_status; user.beta_status = payload.status
        audit_admin(session, admin.id, "beta_status_change", "user", user_id, request.state.request_id, {"previous": previous, "status": payload.status})
        return {"id": user.id, "beta_status": user.beta_status}


@router.post("/admin/product/users/{user_id}/notes", status_code=201)
async def add_beta_note(user_id: str, payload: BetaNoteRequest, request: Request, admin=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        if not session.get(User, user_id): raise AppError("User not found.", "USER_NOT_FOUND", 404)
        note = BetaUserNote(user_id=user_id, author_user_id=admin.id, note=payload.note.strip()); session.add(note); session.flush()
        response = {"id": note.id, "user_id": user_id, "author_user_id": admin.id, "note": note.note, "created_at": note.created_at}
        audit_admin(session, admin.id, "beta_note_added", "user", user_id, request.state.request_id, {"note_id": note.id})
        return response


@router.get("/admin/product/users/{user_id}/notes")
async def list_beta_notes(user_id: str, _=Depends(require_system_admin)) -> list[dict]:
    with session_scope() as session:
        items = session.scalars(select(BetaUserNote).where(BetaUserNote.user_id == user_id).order_by(BetaUserNote.created_at.desc())).all()
        return [{"id": item.id, "user_id": item.user_id, "author_user_id": item.author_user_id, "note": item.note, "created_at": item.created_at} for item in items]
