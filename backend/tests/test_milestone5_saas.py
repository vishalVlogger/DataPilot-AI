from datetime import datetime, timedelta, timezone
from time import sleep

import jwt


def register(client, email: str, name: str = "Tenant User") -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPass123", "display_name": name})
    assert response.status_code == 201, response.text
    payload = response.json()
    return payload, {"Authorization": f"Bearer {payload['access_token']}", "X-Workspace-ID": payload["workspaces"][0]["id"]}


def upload(client, headers: dict[str, str], name: str = "sales.csv") -> str:
    response = client.post("/api/datasets/upload", headers=headers, files={"file": (name, b"Region,Sales\nWest,10\nNorth,20\n", "text/csv")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_auth_lifecycle_rotation_and_protection(anonymous_client) -> None:
    client = anonymous_client
    assert client.get("/api/datasets").status_code == 401
    payload, headers = register(client, "Member@Example.com", "Member")
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/register", json={"email": "member@example.com", "password": "StrongPass123", "display_name": "Duplicate"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "member@example.com", "password": "wrong"}).status_code == 401

    cookie_name = "datapilot_refresh"; old_cookie = client.cookies.get(cookie_name)
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(cookie_name) != old_cookie
    replay = type(client)(client.app)
    replay.cookies.set(cookie_name, old_cookie)
    assert replay.post("/api/auth/refresh").status_code == 401
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/refresh").status_code == 401


def test_expired_token_and_disabled_account(anonymous_client) -> None:
    payload, headers = register(anonymous_client, "disabled@example.com")
    from app.core.config import get_settings
    expired = jwt.encode({"sub": payload["user"]["id"], "type": "access", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, get_settings().secret_key, algorithm="HS256")
    response = anonymous_client.get("/api/datasets", headers={**headers, "Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and response.json()["error_code"] == "AUTH_TOKEN_EXPIRED"
    from app.core.database import session_scope
    from app.models import User
    with session_scope() as session:
        user = session.get(User, payload["user"]["id"]); user.is_active = False; session.commit()
    assert anonymous_client.get("/api/datasets", headers=headers).status_code == 403


def test_cross_tenant_dataset_versions_sessions_runs_saved_jobs_and_reports(anonymous_client) -> None:
    client = anonymous_client
    _, a = register(client, "tenant-a@example.com", "Tenant A")
    dataset_id = upload(client, a)
    session = client.post(f"/api/datasets/{dataset_id}/sessions", headers=a, json={"title": "A session"}).json()
    plan = {"operation": "aggregate", "metric": "Sales", "aggregation": "sum", "group_by": [], "filters": [], "sort": None, "limit": 10}
    analyzed = client.post(f"/api/datasets/{dataset_id}/analyze", headers=a, json={"plan": plan, "session_id": session["id"], "question": "Total sales"})
    assert analyzed.status_code == 200
    saved = client.post(f"/api/datasets/{dataset_id}/saved-analyses", headers=a, json={"name": "A saved", "plan": plan}).json()
    job_response = client.post(f"/api/datasets/{dataset_id}/report", headers=a, json={"title": "A report", "format": "html", "async_job": True})
    assert job_response.status_code == 202
    job_id = job_response.json()["job_id"]

    _, b = register(client, "tenant-b@example.com", "Tenant B")
    attempts = [
        client.get(f"/api/datasets/{dataset_id}", headers=b),
        client.get(f"/api/datasets/{dataset_id}/versions", headers=b),
        client.get(f"/api/sessions/{session['id']}", headers=b),
        client.get(f"/api/sessions/{session['id']}/runs", headers=b),
        client.post(f"/api/saved-analyses/{saved['id']}/run", headers=b),
        client.get(f"/api/jobs/{job_id}", headers=b),
        client.get(f"/api/jobs/{job_id}/result", headers=b),
        client.post(f"/api/datasets/{dataset_id}/report", headers=b, json={"title": "stolen", "format": "html"}),
    ]
    assert all(response.status_code == 404 for response in attempts), [(response.status_code, response.text) for response in attempts]
    assert client.get("/api/datasets", headers=b).json() == []


def test_usage_activity_quota_search_pagination_and_rename(anonymous_client, monkeypatch) -> None:
    client = anonymous_client; _, headers = register(client, "usage@example.com")
    from app.services.saas import PLANS, PlanDefinition
    monkeypatch.setitem(PLANS, "free", PlanDefinition(1, 100 * 1024 * 1024, 1024 * 1024, 100, 2, 1, 2))
    dataset_id = upload(client, headers, "quarterly-sales.csv")
    renamed = client.patch(f"/api/datasets/{dataset_id}", headers=headers, json={"name": "FY Sales.csv"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "FY Sales.csv"
    assert len(client.get("/api/datasets?search=FY&limit=1&offset=0", headers=headers).json()) == 1
    blocked = client.post("/api/datasets/upload", headers=headers, files={"file": ("second.csv", b"x\n1\n", "text/csv")})
    assert blocked.status_code == 403 and blocked.json()["error_code"] == "QUOTA_DATASET_LIMIT"
    usage = client.get("/api/usage", headers=headers).json()
    assert usage["datasets"] == 1 and usage["rows_this_month"] == 2 and usage["storage_bytes"] > 0
    activity = client.get("/api/activity", headers=headers).json()
    assert {item["activity_type"] for item in activity} >= {"dataset_uploaded", "dataset_renamed"}
    client.delete(f"/api/datasets/{dataset_id}", headers=headers)
    assert client.get("/api/usage", headers=headers).json()["storage_bytes"] == 0


def test_auth_rate_limit_returns_standard_error(anonymous_client) -> None:
    for _ in range(10):
        assert anonymous_client.post("/api/auth/login", json={"email": "none@example.com", "password": "invalid"}).status_code == 401
    response = anonymous_client.post("/api/auth/login", json={"email": "none@example.com", "password": "invalid"})
    assert response.status_code == 429 and response.json()["error_code"] == "RATE_LIMITED"


def test_security_headers_and_readiness(anonymous_client) -> None:
    response = anonymous_client.get("/api/ready")
    assert response.status_code == 200 and response.json()["status"] == "ready"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers.get("x-request-id")
