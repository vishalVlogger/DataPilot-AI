from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.services.object_storage import LocalObjectStorage, safe_object_key
from app.services.workspace_lifecycle import process_due_deletions


def test_local_object_storage_round_trip_and_rejects_traversal(tmp_path) -> None:
    storage = LocalObjectStorage(tmp_path / "objects")
    checksum = storage.put("workspaces/one/report.txt", b"private report", "text/plain")
    assert len(checksum) == 64
    assert storage.get("workspaces/one/report.txt") == b"private report"
    assert list(storage.list("workspaces/one")) == ["workspaces/one/report.txt"]
    try:
        safe_object_key("../secrets.txt")
        assert False, "traversal key should be rejected"
    except Exception as exc:
        assert getattr(exc, "error_code", None) == "STORAGE_KEY_INVALID"


def test_production_readiness_rejects_unsafe_defaults() -> None:
    settings = Settings(_env_file=None, app_env="production", secret_key="short", database_url="sqlite:///unsafe.db", email_provider="console")
    errors = settings.readiness_errors()
    assert any("SECRET_KEY" in error for error in errors)
    assert any("PostgreSQL" in error for error in errors)
    assert any("Console email" in error for error in errors)


def test_workspace_deletion_is_read_only_cancelable_and_processed(client) -> None:
    workspace = client.get("/api/workspaces").json()[0]
    scheduled = client.post(f"/api/workspaces/{workspace['id']}/deletion-request", json={"confirmation": workspace["name"]})
    assert scheduled.status_code == 202
    blocked = client.patch(f"/api/workspaces/{workspace['id']}", json={"name": "Should not change"})
    assert blocked.status_code == 409
    cancelled = client.delete(f"/api/workspaces/{workspace['id']}/deletion-request")
    assert cancelled.status_code == 200 and cancelled.json()["cancelled"] is True

    client.post(f"/api/workspaces/{workspace['id']}/deletion-request", json={"confirmation": workspace["name"]})
    result = process_due_deletions(datetime.now(timezone.utc) + timedelta(days=30))
    assert result["workspaces_deleted"] == 1
    assert client.get("/api/workspaces").json() == []


def test_password_confirmed_account_deletion_revokes_access_and_observes_grace_period(client) -> None:
    me = client.get("/api/auth/me").json(); workspace = me["workspaces"][0]; user_id = me["user"]["id"]
    assert client.post(f"/api/workspaces/{workspace['id']}/deletion-request", json={"confirmation": workspace["name"]}).status_code == 202
    requested = client.post("/api/auth/deletion-request", json={"password": "Testing12345"})
    assert requested.status_code == 202
    assert client.get("/api/auth/me").status_code == 403

    result = process_due_deletions(datetime.now(timezone.utc) + timedelta(days=30))
    assert result == {"workspaces_deleted": 1, "accounts_deleted": 1}
    from app.core.database import session_scope
    from app.models import User
    with session_scope() as session: assert session.get(User, user_id) is None
