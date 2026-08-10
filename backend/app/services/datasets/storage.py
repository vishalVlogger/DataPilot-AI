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
        frame.to_pickle(folder / "original.pkl")
        frame.to_pickle(folder / "data.pkl")
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
        path = self.root / dataset_id / "original.pkl"
        if not path.is_file():
            raise DatasetNotFoundError()
        frame = pd.read_pickle(path)
        self.save_working_frame(dataset_id, frame)
        self._write_audit(dataset_id, [])
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
