import time
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from pypdf import PdfReader

from app.schemas.dataset import AnalysisPlan
from app.services.analytics.engines.duckdb_engine import DuckDBExecutionEngine
from app.services.datasets.storage import DatasetStorage


def upload(client) -> str:
    response = client.post(
        "/api/datasets/upload",
        files={"file": ("sales.csv", b"Region,Product,Sales\nWest,A,10\nWest,B,20\nNorth,A,30\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_duckdb_scans_parquet_without_pandas_materialization(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "large.parquet"
    pd.DataFrame({"Region": ["West", "North", "West"], "Sales": [10, 20, 30]}).to_parquet(path)
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full load")))
    plan = AnalysisPlan(operation="group_and_aggregate", metric="Sales", aggregation="sum", group_by=["Region"])
    result = await DuckDBExecutionEngine().execute_plan(path, plan)
    assert result.engine == "duckdb"
    assert result.result == [{"Region": "West", "Sales": 40.0}, {"Region": "North", "Sales": 20.0}]


def test_parquet_storage_database_library_sessions_saved_and_cascade_delete(client, tmp_path: Path) -> None:
    dataset_id = upload(client)
    parquet = tmp_path / "data" / dataset_id / "versions" / "version_0.parquet"
    assert parquet.is_file()
    library = client.get("/api/datasets")
    assert library.status_code == 200 and library.json()[0]["storage_format"] == "parquet"

    session = client.post(f"/api/datasets/{dataset_id}/sessions", json={"title": "Quarterly review"})
    assert session.status_code == 201
    session_id = session.json()["id"]
    analysis = client.post(f"/api/datasets/{dataset_id}/analyze", json={
        "session_id": session_id,
        "question": "Sales by region",
        "plan": {"operation": "group_and_aggregate", "metric": "Sales", "aggregation": "sum", "group_by": ["Region"]},
    })
    assert analysis.status_code == 200 and analysis.json()["metadata"]["session_id"] == session_id
    runs = client.get(f"/api/sessions/{session_id}/runs")
    assert runs.status_code == 200 and runs.json()[0]["dataset_version"] == 0

    saved = client.post(f"/api/datasets/{dataset_id}/saved-analyses", json={
        "name": "Regional sales",
        "plan": {"operation": "group_and_aggregate", "metric": "Sales", "aggregation": "sum", "group_by": ["Region"]},
        "chart_config": {"type": "bar"},
    })
    assert saved.status_code == 201
    rerun = client.post(f"/api/saved-analyses/{saved.json()['id']}/run")
    assert rerun.status_code == 200
    assert {row["Region"]: row["Sales"] for row in rerun.json()["result"]} == {"West": 30, "North": 30}

    deleted = client.delete(f"/api/datasets/{dataset_id}")
    assert deleted.status_code == 204 and not parquet.parent.parent.exists()
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_pdf_report_and_background_job(client) -> None:
    dataset_id = upload(client)
    direct = client.post(f"/api/datasets/{dataset_id}/report", json={"title": "Sales PDF", "format": "pdf", "include_version_history": True})
    assert direct.status_code == 200 and direct.headers["content-type"] == "application/pdf"
    reader = PdfReader(__import__("io").BytesIO(direct.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Sales PDF" in text and "Dataset overview" in text and "Version history" in text

    accepted = client.post(f"/api/datasets/{dataset_id}/report", json={"title": "Async PDF", "format": "pdf", "async_job": True})
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    states = []
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}")
        assert job.status_code == 200
        states.append(job.json()["status"])
        if states[-1] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert states[-1] == "completed"
    assert job.json()["progress"] == 100 and job.json()["result_reference"] == f"/api/jobs/{job_id}/result"
    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200 and result.content.startswith(b"%PDF")


def test_drilldown_adds_filter_and_breadcrumb(client) -> None:
    dataset_id = upload(client)
    response = client.post(f"/api/datasets/{dataset_id}/drilldown", json={
        "base_plan": {"operation": "group_and_aggregate", "metric": "Sales", "aggregation": "sum", "group_by": ["Region"]},
        "clicked_dimension": "Region", "clicked_value": "West", "next_dimension": "Product", "breadcrumb": [],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["breadcrumb"] == ["Region: West"]
    assert {row["Product"]: row["Sales"] for row in body["result"]} == {"A": 10, "B": 20}


def test_legacy_pickle_is_lazily_migrated(tmp_path: Path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.core.database import reset_database_engine
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    get_settings.cache_clear(); reset_database_engine()
    dataset_id = str(uuid4()); folder = tmp_path / dataset_id; folder.mkdir()
    frame = pd.DataFrame({"Sales": [1, 2]}); frame.to_pickle(folder / "original.pkl")
    (folder / "metadata.json").write_text(__import__("json").dumps({
        "id": dataset_id, "name": "legacy.csv", "source_type": "csv", "sheet_name": None,
        "rows": 2, "columns": 1, "created_at": "2026-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    store = DatasetStorage(tmp_path)
    assert store.load_frame(dataset_id)["Sales"].sum() == 3
    assert (folder / "versions" / "version_0.parquet").is_file()
