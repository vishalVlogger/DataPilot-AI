from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, DatasetNotFoundError
from app.models import AnalysisRun, AnalysisSession, Dataset, DatasetVersion, Job, SavedAnalysis


def _dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


class ScopedRepository:
    def __init__(self, session: Session, workspace_id: str | None = None) -> None:
        self.session = session; self.workspace_id = workspace_id or get_settings().legacy_workspace_id


class DatasetRepository(ScopedRepository):
    def create(self, **values: Any) -> Dataset:
        values.setdefault("workspace_id", self.workspace_id); model = Dataset(**values); self.session.add(model); self.session.commit(); return model
    def upsert(self, dataset_id: str, **values: Any) -> Dataset:
        model = self.session.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.workspace_id == self.workspace_id))
        if model is None: return self.create(id=dataset_id, **values)
        for key, value in values.items(): setattr(model, key, value)
        self.session.commit(); return model
    def get_any(self, dataset_id: str) -> Dataset | None:
        return self.session.get(Dataset, dataset_id)
    def get(self, dataset_id: str) -> Dataset:
        model = self.session.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.workspace_id == self.workspace_id))
        if model is None: raise DatasetNotFoundError()
        return model
    def list(self, limit: int = 50, offset: int = 0, search: str | None = None, source_type: str | None = None, recently_analyzed: bool = False) -> list[dict[str, Any]]:
        query = select(Dataset).where(Dataset.workspace_id == self.workspace_id)
        if search: query = query.where(Dataset.name.ilike(f"%{search[:100]}%"))
        if source_type: query = query.where(Dataset.source_type == source_type)
        ordering = Dataset.last_analyzed_at.desc().nullslast() if recently_analyzed else Dataset.created_at.desc()
        return [_dict(item) for item in self.session.scalars(query.order_by(ordering).limit(limit).offset(offset)).all()]
    def update_profile(self, dataset_id: str, profile: dict[str, Any]) -> None:
        model = self.get(dataset_id); model.profile_summary = profile; model.updated_at = datetime.now(timezone.utc); self.session.commit()
    def mark_analyzed(self, dataset_id: str) -> None:
        model = self.get(dataset_id); model.last_analyzed_at = datetime.now(timezone.utc); self.session.commit()
    def rename(self, dataset_id: str, name: str) -> Dataset:
        model = self.get(dataset_id); model.name = name; model.updated_at = datetime.now(timezone.utc); self.session.commit(); return model
    def update_storage(self, dataset_id: str, storage_bytes: int) -> None:
        model = self.get(dataset_id); model.storage_bytes = storage_bytes; model.updated_at = datetime.now(timezone.utc); self.session.commit()
    def delete(self, dataset_id: str) -> None:
        model = self.get(dataset_id); self.session.delete(model); self.session.commit()


class DatasetVersionRepository(ScopedRepository):
    def create(self, **values: Any) -> DatasetVersion:
        values.setdefault("workspace_id", self.workspace_id)
        DatasetRepository(self.session, self.workspace_id).get(values["dataset_id"])
        if values.get("is_current"):
            self.session.execute(update(DatasetVersion).where(DatasetVersion.dataset_id == values["dataset_id"], DatasetVersion.workspace_id == self.workspace_id).values(is_current=False))
        model = DatasetVersion(**values); self.session.add(model); dataset = DatasetRepository(self.session, self.workspace_id).get(values["dataset_id"])
        if values.get("is_current"): dataset.current_version = values["version"]
        self.session.commit(); return model
    def list(self, dataset_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        DatasetRepository(self.session, self.workspace_id).get(dataset_id)
        query = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.workspace_id == self.workspace_id).order_by(DatasetVersion.version).limit(limit).offset(offset)
        return [_dict(item) for item in self.session.scalars(query).all()]
    def get(self, dataset_id: str, version: int) -> DatasetVersion:
        model = self.session.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.version == version, DatasetVersion.workspace_id == self.workspace_id))
        if model is None: raise DatasetNotFoundError()
        return model


class AnalysisSessionRepository(ScopedRepository):
    def create(self, dataset_id: str, version: int, title: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        DatasetRepository(self.session, self.workspace_id).get(dataset_id); model = AnalysisSession(workspace_id=self.workspace_id, user_id=user_id, dataset_id=dataset_id, current_dataset_version=version, title=title); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, dataset_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        DatasetRepository(self.session, self.workspace_id).get(dataset_id); query = select(AnalysisSession).where(AnalysisSession.dataset_id == dataset_id, AnalysisSession.workspace_id == self.workspace_id).order_by(AnalysisSession.last_activity_at.desc()).limit(limit).offset(offset)
        return [_dict(item) for item in self.session.scalars(query).all()]
    def get(self, session_id: str) -> dict[str, Any]:
        model = self.session.scalar(select(AnalysisSession).where(AnalysisSession.id == session_id, AnalysisSession.workspace_id == self.workspace_id))
        if model is None: raise AppError("Analysis session not found.", "SESSION_NOT_FOUND", 404)
        return _dict(model)
    def touch(self, session_id: str, version: int) -> None:
        model = self.session.scalar(select(AnalysisSession).where(AnalysisSession.id == session_id, AnalysisSession.workspace_id == self.workspace_id))
        if model: model.last_activity_at = datetime.now(timezone.utc); model.current_dataset_version = version; self.session.commit()


class AnalysisRunRepository(ScopedRepository):
    def create(self, **values: Any) -> dict[str, Any]:
        values.setdefault("workspace_id", self.workspace_id); DatasetRepository(self.session, self.workspace_id).get(values["dataset_id"]); model = AnalysisRun(**values); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, session_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        AnalysisSessionRepository(self.session, self.workspace_id).get(session_id); query = select(AnalysisRun).where(AnalysisRun.session_id == session_id, AnalysisRun.workspace_id == self.workspace_id).order_by(AnalysisRun.created_at.desc()).limit(limit).offset(offset)
        return [_dict(item) for item in self.session.scalars(query).all()]


class SavedAnalysisRepository(ScopedRepository):
    def create(self, dataset_id: str, name: str, query_plan: dict[str, Any], chart_config: dict[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
        DatasetRepository(self.session, self.workspace_id).get(dataset_id); model = SavedAnalysis(workspace_id=self.workspace_id, user_id=user_id, dataset_id=dataset_id, name=name, query_plan=query_plan, chart_config=chart_config); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, dataset_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        DatasetRepository(self.session, self.workspace_id).get(dataset_id); query = select(SavedAnalysis).where(SavedAnalysis.dataset_id == dataset_id, SavedAnalysis.workspace_id == self.workspace_id).order_by(SavedAnalysis.updated_at.desc()).limit(limit).offset(offset)
        return [_dict(item) for item in self.session.scalars(query).all()]
    def get(self, analysis_id: str) -> SavedAnalysis:
        model = self.session.scalar(select(SavedAnalysis).where(SavedAnalysis.id == analysis_id, SavedAnalysis.workspace_id == self.workspace_id))
        if model is None: raise AppError("Saved analysis not found.", "SAVED_ANALYSIS_INVALID", 404)
        return model
    def delete(self, analysis_id: str) -> None:
        model = self.get(analysis_id); self.session.delete(model); self.session.commit()


class JobRepository(ScopedRepository):
    def create(self, job_type: str, dataset_id: str | None, stage: str = "queued", user_id: str | None = None, **values: Any) -> dict[str, Any]:
        if dataset_id: DatasetRepository(self.session, self.workspace_id).get(dataset_id)
        model = Job(workspace_id=self.workspace_id, user_id=user_id, type=job_type, dataset_id=dataset_id, stage=stage, **values); self.session.add(model); self.session.commit(); return _dict(model)
    def get(self, job_id: str) -> dict[str, Any]:
        model = self.session.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == self.workspace_id))
        if model is None: raise AppError("Background job not found.", "JOB_NOT_FOUND", 404)
        return _dict(model)
    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(Job).where(Job.workspace_id == self.workspace_id).order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()]
    def update(self, job_id: str, **values: Any) -> dict[str, Any]:
        model = self.session.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == self.workspace_id))
        if model is None: raise AppError("Background job not found.", "JOB_NOT_FOUND", 404)
        for key, value in values.items(): setattr(model, key, value)
        self.session.commit(); return _dict(model)
