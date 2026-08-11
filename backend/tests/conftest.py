import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    os.environ["DATA_STORAGE_DIR"] = str(tmp_path / "data")
    os.environ["DATASET_STORAGE_ROOT"] = str(tmp_path / "data")
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'datapilot.db').as_posix()}"
    from app.core.config import get_settings
    from app.core.database import reset_database_engine
    get_settings.cache_clear()
    reset_database_engine()
    from app.main import app
    return TestClient(app)
