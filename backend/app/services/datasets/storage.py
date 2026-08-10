import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.errors import DatasetNotFoundError


class DatasetStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, frame: pd.DataFrame, name: str, source_type: str, sheet_name: str | None) -> dict[str, Any]:
        dataset_id = str(uuid4())
        folder = self.root / dataset_id
        folder.mkdir(parents=True)
        versions_folder = folder / "versions"
        versions_folder.mkdir()
        frame.to_pickle(folder / "original.pkl")
        frame.to_pickle(folder / "data.pkl")
        frame.to_pickle(versions_folder / "0.pkl")
        metadata: dict[str, Any] = {
            "id": dataset_id,
            "name": Path(name).name,
            "source_type": source_type,
            "sheet_name": sheet_name,
            "rows": len(frame),
            "columns": len(frame.columns),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (folder / "audit.json").write_text("[]", encoding="utf-8")
        version_metadata = {"current_version": 0, "versions": [{"version": 0, "created_at": metadata["created_at"], "operation": "upload", "description": "Original uploaded dataset", "affected_rows": 0, "source_version": None}]}
        (folder / "versions.json").write_text(json.dumps(version_metadata), encoding="utf-8")
        return metadata

    def load_frame(self, dataset_id: str) -> pd.DataFrame:
        path = self.root / dataset_id / "data.pkl"
        if not path.is_file():
            raise DatasetNotFoundError()
        return pd.read_pickle(path)

    def load_metadata(self, dataset_id: str) -> dict[str, Any]:
        path = self.root / dataset_id / "metadata.json"
        if not path.is_file():
            raise DatasetNotFoundError()
        return json.loads(path.read_text(encoding="utf-8"))

    def save_working_frame(self, dataset_id: str, frame: pd.DataFrame) -> None:
        folder = self.root / dataset_id
        if not folder.is_dir():
            raise DatasetNotFoundError()
        frame.to_pickle(folder / "data.pkl")

    def reset(self, dataset_id: str) -> pd.DataFrame:
        frame, _ = self.restore_version(dataset_id, 0)
        return frame

    def load_original_frame(self, dataset_id: str) -> pd.DataFrame:
        path = self.root / dataset_id / "original.pkl"
        if not path.is_file():
            raise DatasetNotFoundError()
        return pd.read_pickle(path)

    def load_audit(self, dataset_id: str) -> list[dict[str, Any]]:
        path = self.root / dataset_id / "audit.json"
        if not path.is_file():
            raise DatasetNotFoundError()
        return json.loads(path.read_text(encoding="utf-8"))

    def append_audit(self, dataset_id: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        audit = self.load_audit(dataset_id)
        audit.extend(entries)
        self._write_audit(dataset_id, audit)
        return audit

    def _write_audit(self, dataset_id: str, audit: list[dict[str, Any]]) -> None:
        (self.root / dataset_id / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    def list_versions(self, dataset_id: str) -> dict[str, Any]:
        path = self.root / dataset_id / "versions.json"
        if not path.is_file():
            raise DatasetNotFoundError()
        metadata = json.loads(path.read_text(encoding="utf-8"))
        for item in metadata["versions"]:
            item["is_current"] = item["version"] == metadata["current_version"]
        return metadata

    def current_version(self, dataset_id: str) -> int:
        return int(self.list_versions(dataset_id)["current_version"])

    def create_version(self, dataset_id: str, frame: pd.DataFrame, operation: str, description: str, affected_rows: int = 0, source_version: int | None = None) -> int:
        folder = self.root / dataset_id
        metadata = self.list_versions(dataset_id)
        version = max(item["version"] for item in metadata["versions"]) + 1
        source = metadata["current_version"] if source_version is None else source_version
        frame.to_pickle(folder / "versions" / f"{version}.pkl")
        frame.to_pickle(folder / "data.pkl")
        metadata["current_version"] = version
        metadata["versions"].append({"version": version, "created_at": datetime.now(timezone.utc).isoformat(), "operation": operation, "description": description, "affected_rows": affected_rows, "source_version": source})
        for item in metadata["versions"]:
            item.pop("is_current", None)
        (folder / "versions.json").write_text(json.dumps(metadata), encoding="utf-8")
        return version

    def load_version(self, dataset_id: str, version: int) -> pd.DataFrame:
        path = self.root / dataset_id / "versions" / f"{version}.pkl"
        if not path.is_file():
            raise DatasetNotFoundError()
        return pd.read_pickle(path)

    def restore_version(self, dataset_id: str, version: int) -> tuple[pd.DataFrame, int]:
        frame = self.load_version(dataset_id, version)
        new_version = self.create_version(dataset_id, frame, "restore", f"Restored dataset version {version}", 0, source_version=version)
        self.append_audit(dataset_id, [{"operation": "restore", "target_column": None, "affected_row_count": 0, "timestamp": datetime.now(timezone.utc).isoformat(), "source_version": version, "version": new_version}])
        return frame, new_version
