import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    os.environ["DATA_STORAGE_DIR"] = str(tmp_path / "data")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    return TestClient(app)
