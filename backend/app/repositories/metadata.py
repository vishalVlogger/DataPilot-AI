from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, DatasetNotFoundError
from app.models import AnalysisRun, AnalysisSession, Dataset, DatasetVersion, Job, SavedAnalysis


def _dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


class DatasetRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, **values: Any) -> Dataset:
        model = Dataset(**values); self.session.add(model); self.session.commit(); return model
    def upsert(self, dataset_id: str, **values: Any) -> Dataset:
        model = self.session.get(Dataset, dataset_id)
        if model is None: return self.create(id=dataset_id, **values)
        for key, value in values.items(): setattr(model, key, value)
        self.session.commit(); return model
    def get(self, dataset_id: str) -> Dataset:
        model = self.session.get(Dataset, dataset_id)
        if model is None: raise DatasetNotFoundError()
        return model
    def list(self) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(Dataset).order_by(Dataset.created_at.desc())).all()]
    def update_profile(self, dataset_id: str, profile: dict[str, Any]) -> None:
        model = self.get(dataset_id); model.profile_summary = profile; model.updated_at = datetime.now(timezone.utc); self.session.commit()
    def mark_analyzed(self, dataset_id: str) -> None:
        model = self.get(dataset_id); model.last_analyzed_at = datetime.now(timezone.utc); self.session.commit()
    def delete(self, dataset_id: str) -> None:
        model = self.get(dataset_id); self.session.delete(model); self.session.commit()


class DatasetVersionRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, **values: Any) -> DatasetVersion:
        if values.get("is_current"):
            self.session.execute(update(DatasetVersion).where(DatasetVersion.dataset_id == values["dataset_id"]).values(is_current=False))
        model = DatasetVersion(**values); self.session.add(model)
        dataset = self.session.get(Dataset, values["dataset_id"])
        if dataset and values.get("is_current"): dataset.current_version = values["version"]
        self.session.commit(); return model
    def list(self, dataset_id: str) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version)).all()]
    def get(self, dataset_id: str, version: int) -> DatasetVersion:
        model = self.session.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.version == version))
        if model is None: raise DatasetNotFoundError()
        return model


class AnalysisSessionRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, dataset_id: str, version: int, title: str | None = None) -> dict[str, Any]:
        model = AnalysisSession(dataset_id=dataset_id, current_dataset_version=version, title=title); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, dataset_id: str) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(AnalysisSession).where(AnalysisSession.dataset_id == dataset_id).order_by(AnalysisSession.last_activity_at.desc())).all()]
    def get(self, session_id: str) -> dict[str, Any]:
        model = self.session.get(AnalysisSession, session_id)
        if model is None: raise AppError("Analysis session not found.", "SESSION_NOT_FOUND", 404)
        return _dict(model)
    def touch(self, session_id: str, version: int) -> None:
        model = self.session.get(AnalysisSession, session_id)
        if model: model.last_activity_at = datetime.now(timezone.utc); model.current_dataset_version = version; self.session.commit()


class AnalysisRunRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, **values: Any) -> dict[str, Any]:
        model = AnalysisRun(**values); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, session_id: str) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(AnalysisRun).where(AnalysisRun.session_id == session_id).order_by(AnalysisRun.created_at)).all()]


class SavedAnalysisRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, dataset_id: str, name: str, query_plan: dict[str, Any], chart_config: dict[str, Any] | None) -> dict[str, Any]:
        model = SavedAnalysis(dataset_id=dataset_id, name=name, query_plan=query_plan, chart_config=chart_config); self.session.add(model); self.session.commit(); return _dict(model)
    def list(self, dataset_id: str) -> list[dict[str, Any]]:
        return [_dict(item) for item in self.session.scalars(select(SavedAnalysis).where(SavedAnalysis.dataset_id == dataset_id).order_by(SavedAnalysis.updated_at.desc())).all()]
    def get(self, analysis_id: str) -> SavedAnalysis:
        model = self.session.get(SavedAnalysis, analysis_id)
        if model is None: raise AppError("Saved analysis not found.", "SAVED_ANALYSIS_INVALID", 404)
        return model
    def delete(self, analysis_id: str) -> None:
        model = self.get(analysis_id); self.session.delete(model); self.session.commit()


class JobRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, job_type: str, dataset_id: str | None, stage: str = "queued") -> dict[str, Any]:
        model = Job(type=job_type, dataset_id=dataset_id, stage=stage); self.session.add(model); self.session.commit(); return _dict(model)
    def get(self, job_id: str) -> dict[str, Any]:
        model = self.session.get(Job, job_id)
        if model is None: raise AppError("Background job not found.", "JOB_NOT_FOUND", 404)
        return _dict(model)
    def update(self, job_id: str, **values: Any) -> dict[str, Any]:
        model = self.session.get(Job, job_id)
        if model is None: raise AppError("Background job not found.", "JOB_NOT_FOUND", 404)
        for key, value in values.items(): setattr(model, key, value)
        self.session.commit(); return _dict(model)
