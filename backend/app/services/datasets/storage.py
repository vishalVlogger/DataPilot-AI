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
