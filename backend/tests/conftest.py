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
    from app.core.rate_limit import rate_limiter
    rate_limiter.clear()
    from app.main import app
    test_client = TestClient(app)
    response = test_client.post("/api/auth/register", json={"email": "existing-tests@example.com", "password": "Testing12345", "display_name": "Existing Tests"})
    assert response.status_code == 201, response.text
    payload = response.json()
    test_client.headers.update({"Authorization": f"Bearer {payload['access_token']}", "X-Workspace-ID": payload["workspaces"][0]["id"]})
    return test_client


@pytest.fixture()
def anonymous_client(tmp_path: Path) -> TestClient:
    os.environ["DATA_STORAGE_DIR"] = str(tmp_path / "anonymous-data")
    os.environ["DATASET_STORAGE_ROOT"] = str(tmp_path / "anonymous-data")
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'anonymous.db').as_posix()}"
    from app.core.config import get_settings
    from app.core.database import reset_database_engine
    from app.core.rate_limit import rate_limiter
    get_settings.cache_clear(); reset_database_engine(); rate_limiter.clear()
    from app.main import app
    return TestClient(app)
