from typing import Any


class AnalysisCache:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._values.get(key)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def invalidate_dataset(self, dataset_id: str) -> None:
        for key in [item for item in self._values if item.startswith(f"{dataset_id}:")]:
            self._values.pop(key, None)


analysis_cache = AnalysisCache()
