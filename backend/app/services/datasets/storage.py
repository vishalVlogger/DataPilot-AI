import json
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError, DatasetNotFoundError
from app.repositories import DatasetRepository, DatasetVersionRepository


class DatasetStorageBackend(ABC):
    @abstractmethod
    def save(self, frame: pd.DataFrame, name: str, source_type: str, sheet_name: str | None, original_content: bytes | None = None) -> dict[str, Any]: ...
    @abstractmethod
    def load_frame(self, dataset_id: str) -> pd.DataFrame: ...
    @abstractmethod
    def get_dataset_path(self, dataset_id: str, version: int | None = None) -> Path: ...
    @abstractmethod
    def create_version(self, dataset_id: str, frame: pd.DataFrame, operation: str, description: str, affected_rows: int = 0, source_version: int | None = None) -> int: ...


class LocalParquetDatasetStorage(DatasetStorageBackend):
    def __init__(self, root: Path, compression: str | None = None, workspace_id: str | None = None, user_id: str | None = None) -> None:
        self.root = root.resolve()
        self.compression = compression or get_settings().parquet_compression
        self.workspace_id = workspace_id or get_settings().legacy_workspace_id
        self.user_id = user_id
        self.root.mkdir(parents=True, exist_ok=True)

    def _folder(self, dataset_id: str) -> Path:
        if not dataset_id or any(character not in "0123456789abcdef-" for character in dataset_id.lower()):
            raise DatasetNotFoundError()
        if not self.workspace_id or any(character not in "0123456789abcdef-" for character in self.workspace_id.lower()): raise DatasetNotFoundError()
        legacy = (self.root / dataset_id).resolve()
        tenant_folder = (self.root / "workspaces" / self.workspace_id / dataset_id).resolve()
        folder = tenant_folder if tenant_folder.is_dir() else legacy if legacy.is_dir() else tenant_folder
        if self.root not in folder.parents:
            raise DatasetNotFoundError()
        return folder

    def _create_legacy_parquet_alias(self, dataset_id: str, version_path: Path) -> None:
        """Keep the pre-Milestone-6 local path readable while tenant storage is canonical."""
        alias = self.root / dataset_id / "versions" / version_path.name
        alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            alias.hardlink_to(version_path)
        except OSError:
            shutil.copy2(version_path, alias)

    def _write_parquet(self, frame: pd.DataFrame, path: Path) -> None:
        try:
            frame.to_parquet(path, index=False, compression=self.compression)
        except Exception as exc:
            raise AppError("Unable to write normalized Parquet storage.", "PARQUET_CONVERSION_FAILED", 500) from exc

    def save(self, frame: pd.DataFrame, name: str, source_type: str, sheet_name: str | None, original_content: bytes | None = None) -> dict[str, Any]:
        dataset_id = str(uuid4()); folder = self._folder(dataset_id); versions = folder / "versions"
        try:
            versions.mkdir(parents=True)
            version_path = versions / "version_0.parquet"
            self._write_parquet(frame, version_path)
            self._create_legacy_parquet_alias(dataset_id, version_path)
            if original_content is not None:
                extension = Path(name).suffix.lower() if Path(name).suffix else ".bin"
                (folder / f"original{extension}").write_bytes(original_content)
        except AppError: raise
        except Exception as exc:
            raise AppError("Unable to persist the uploaded dataset.", "STORAGE_WRITE_FAILED", 500) from exc
        now = datetime.now(timezone.utc)
        metadata: dict[str, Any] = {"id": dataset_id, "workspace_id": self.workspace_id, "name": Path(name).name, "source_type": source_type, "sheet_name": sheet_name, "rows": len(frame), "columns": len(frame.columns), "created_at": now.isoformat(), "updated_at": now.isoformat(), "current_version": 0, "storage_format": "parquet", "storage_key": str(version_path.relative_to(self.root)).replace("\\", "/"), "status": "ready", "storage_bytes": 0}
        (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (folder / "audit.json").write_text("[]", encoding="utf-8")
        (folder / "versions.json").write_text(json.dumps({"current_version": 0, "versions": [{"version": 0, "created_at": now.isoformat(), "operation": "upload", "description": "Original uploaded dataset", "affected_rows": 0, "source_version": None, "storage_key": metadata["storage_key"]}]}), encoding="utf-8")
        storage_bytes = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
        metadata["storage_bytes"] = storage_bytes
        (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        with session_scope() as session:
            DatasetRepository(session, self.workspace_id).create(id=dataset_id, uploader_user_id=self.user_id, name=Path(name).name, original_filename=Path(name).name, source_type=source_type, sheet_name=sheet_name, row_count=len(frame), column_count=len(frame.columns), created_at=now, updated_at=now, current_version=0, storage_format="parquet", storage_key=metadata["storage_key"], status="ready", storage_bytes=storage_bytes)
            DatasetVersionRepository(session, self.workspace_id).create(dataset_id=dataset_id, version=0, operation="upload", description="Original uploaded dataset", affected_rows=0, storage_key=metadata["storage_key"], is_current=True)
        return metadata

    def _legacy_metadata(self, dataset_id: str) -> dict[str, Any]:
        path = self._folder(dataset_id) / "metadata.json"
        if not path.is_file(): raise DatasetNotFoundError()
        return json.loads(path.read_text(encoding="utf-8"))

    def _ensure_database_record(self, dataset_id: str) -> None:
        with session_scope() as session:
            repository = DatasetRepository(session, self.workspace_id)
            existing = repository.get_any(dataset_id)
            if existing is not None:
                if existing.workspace_id != self.workspace_id: raise DatasetNotFoundError()
                return
            if self.workspace_id != get_settings().legacy_workspace_id: raise DatasetNotFoundError()
            metadata = self._legacy_metadata(dataset_id); path = self._ensure_parquet(dataset_id)
            created = datetime.fromisoformat(metadata["created_at"])
            repository.create(id=dataset_id, uploader_user_id=self.user_id, name=metadata["name"], original_filename=metadata["name"], source_type=metadata["source_type"], sheet_name=metadata.get("sheet_name"), row_count=metadata["rows"], column_count=metadata["columns"], created_at=created, updated_at=created, current_version=self._legacy_versions(dataset_id)["current_version"], storage_format="parquet", storage_key=str(path.relative_to(self.root)).replace("\\", "/"), status="ready", storage_bytes=sum(item.stat().st_size for item in self._folder(dataset_id).rglob("*") if item.is_file()))
            version_repo = DatasetVersionRepository(session, self.workspace_id)
            for item in self._legacy_versions(dataset_id)["versions"]:
                version_path = self._ensure_version_parquet(dataset_id, item["version"])
                version_repo.create(dataset_id=dataset_id, version=item["version"], operation=item["operation"], description=item["description"], affected_rows=item.get("affected_rows", 0), storage_key=str(version_path.relative_to(self.root)).replace("\\", "/"), restored_from_version=item.get("source_version") if item["operation"] == "restore" else None, is_current=item["version"] == self._legacy_versions(dataset_id)["current_version"])

    def _legacy_versions(self, dataset_id: str) -> dict[str, Any]:
        path = self._folder(dataset_id) / "versions.json"
        if path.is_file(): return json.loads(path.read_text(encoding="utf-8"))
        return {"current_version": 0, "versions": [{"version": 0, "created_at": self._legacy_metadata(dataset_id)["created_at"], "operation": "upload", "description": "Original uploaded dataset", "affected_rows": 0, "source_version": None}]}

    def _ensure_version_parquet(self, dataset_id: str, version: int) -> Path:
        folder = self._folder(dataset_id); target = folder / "versions" / f"version_{version}.parquet"
        if target.is_file(): return target
        legacy_candidates = [folder / "versions" / f"{version}.pkl", folder / "original.pkl" if version == 0 else folder / "data.pkl"]
        legacy = next((path for path in legacy_candidates if path.is_file()), None)
        if legacy is None: raise DatasetNotFoundError()
        target.parent.mkdir(exist_ok=True); self._write_parquet(pd.read_pickle(legacy), target)
        return target

    def _ensure_parquet(self, dataset_id: str) -> Path:
        current = self._legacy_versions(dataset_id)["current_version"]
        return self._ensure_version_parquet(dataset_id, current)

    def get_dataset_path(self, dataset_id: str, version: int | None = None) -> Path:
        self._ensure_database_record(dataset_id)
        selected = self.current_version(dataset_id) if version is None else version
        with session_scope() as session:
            record = DatasetVersionRepository(session, self.workspace_id).get(dataset_id, selected)
            path = (self.root / record.storage_key).resolve()
        if self.root not in path.parents or not path.is_file(): raise DatasetNotFoundError()
        return path

    def load_frame(self, dataset_id: str) -> pd.DataFrame:
        try: return pd.read_parquet(self.get_dataset_path(dataset_id))
        except DatasetNotFoundError: raise
        except Exception as exc: raise AppError("Unable to read dataset storage.", "STORAGE_READ_FAILED", 500) from exc

    def load_version(self, dataset_id: str, version: int) -> pd.DataFrame:
        return pd.read_parquet(self.get_dataset_path(dataset_id, version))

    def load_original_frame(self, dataset_id: str) -> pd.DataFrame:
        return self.load_version(dataset_id, 0)

    def load_metadata(self, dataset_id: str) -> dict[str, Any]:
        self._ensure_database_record(dataset_id)
        with session_scope() as session:
            item = DatasetRepository(session, self.workspace_id).get(dataset_id)
            return {"id": item.id, "workspace_id": item.workspace_id, "name": item.name, "source_type": item.source_type, "sheet_name": item.sheet_name, "rows": item.row_count, "columns": item.column_count, "created_at": item.created_at, "updated_at": item.updated_at, "current_version": item.current_version, "storage_format": item.storage_format, "status": item.status, "profile_summary": item.profile_summary, "last_analyzed_at": item.last_analyzed_at, "storage_bytes": item.storage_bytes, "uploader_user_id": item.uploader_user_id}

    def update_profile(self, dataset_id: str, profile: dict[str, Any]) -> None:
        with session_scope() as session: DatasetRepository(session, self.workspace_id).update_profile(dataset_id, profile)

    def list_datasets(self) -> list[dict[str, Any]]:
        with session_scope() as session:
            return DatasetRepository(session, self.workspace_id).list()

    def create_version(self, dataset_id: str, frame: pd.DataFrame, operation: str, description: str, affected_rows: int = 0, source_version: int | None = None) -> int:
        self._ensure_database_record(dataset_id)
        with session_scope() as session:
            dataset = DatasetRepository(session, self.workspace_id).get(dataset_id); version = max([item["version"] for item in DatasetVersionRepository(session, self.workspace_id).list(dataset_id)], default=-1) + 1
        path = self._folder(dataset_id) / "versions" / f"version_{version}.parquet"; self._write_parquet(frame, path)
        key = str(path.relative_to(self.root)).replace("\\", "/")
        with session_scope() as session:
            DatasetVersionRepository(session, self.workspace_id).create(dataset_id=dataset_id, version=version, operation=operation, description=description, affected_rows=affected_rows, storage_key=key, restored_from_version=source_version if operation == "restore" else None, is_current=True)
            DatasetRepository(session, self.workspace_id).update_storage(dataset_id, sum(item.stat().st_size for item in self._folder(dataset_id).rglob("*") if item.is_file()))
        return version

    def restore_version(self, dataset_id: str, version: int) -> tuple[pd.DataFrame, int]:
        frame = self.load_version(dataset_id, version); new_version = self.create_version(dataset_id, frame, "restore", f"Restored dataset version {version}", 0, version)
        self.append_audit(dataset_id, [{"operation": "restore", "target_column": None, "affected_row_count": 0, "timestamp": datetime.now(timezone.utc).isoformat(), "source_version": version, "version": new_version}])
        return frame, new_version

    def reset(self, dataset_id: str) -> pd.DataFrame:
        return self.restore_version(dataset_id, 0)[0]

    def current_version(self, dataset_id: str) -> int:
        self._ensure_database_record(dataset_id)
        with session_scope() as session: return DatasetRepository(session, self.workspace_id).get(dataset_id).current_version

    def list_versions(self, dataset_id: str) -> dict[str, Any]:
        self._ensure_database_record(dataset_id)
        with session_scope() as session:
            dataset = DatasetRepository(session, self.workspace_id).get(dataset_id); items = DatasetVersionRepository(session, self.workspace_id).list(dataset_id)
            return {"current_version": dataset.current_version, "versions": [{"version": item["version"], "created_at": item["created_at"], "operation": item["operation"], "description": item["description"], "affected_rows": item["affected_rows"], "source_version": item["restored_from_version"], "is_current": item["is_current"]} for item in items]}

    def load_audit(self, dataset_id: str) -> list[dict[str, Any]]:
        path = self._folder(dataset_id) / "audit.json"; return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    def append_audit(self, dataset_id: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        audit = self.load_audit(dataset_id); audit.extend(entries); (self._folder(dataset_id) / "audit.json").write_text(json.dumps(audit), encoding="utf-8"); return audit
    def save_working_frame(self, dataset_id: str, frame: pd.DataFrame) -> None:
        self.create_version(dataset_id, frame, "legacy_save", "Saved working dataset")

    def delete_dataset(self, dataset_id: str) -> None:
        folder = self._folder(dataset_id); legacy_alias = self.root / dataset_id; self._ensure_database_record(dataset_id)
        with session_scope() as session: DatasetRepository(session, self.workspace_id).delete(dataset_id)
        try:
            if folder.is_dir(): shutil.rmtree(folder)
            if legacy_alias != folder and legacy_alias.is_dir(): shutil.rmtree(legacy_alias)
        except Exception as exc:
            raise AppError("Metadata was deleted but local files could not be removed.", "STORAGE_WRITE_FAILED", 500) from exc


LocalDatasetStorage = LocalParquetDatasetStorage


def get_dataset_storage(*args, **kwargs) -> DatasetStorageBackend:
    backend = get_settings().dataset_storage_backend.casefold()
    if backend == "local": return LocalDatasetStorage(*args, **kwargs)
    raise AppError("Configured dataset storage backend is unavailable.", "STORAGE_BACKEND_UNAVAILABLE", 503)


DatasetStorage = LocalDatasetStorage
