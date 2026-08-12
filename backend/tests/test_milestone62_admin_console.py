from sqlalchemy import select

from app.models import Feedback, Job, SystemAdminAudit, User


def register(client, email: str, name: str = "Admin Test") -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPass123", "display_name": name, "beta_acknowledged": True})
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}", "X-Workspace-ID": body["workspaces"][0]["id"]}


def promote(email: str) -> str:
    from app.core.database import session_scope
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == email)); user.is_system_admin = True; session.commit(); return user.id


def test_admin_routes_require_system_admin_and_are_paginated(anonymous_client) -> None:
    _, workspace_admin = register(anonymous_client, "workspace-admin@example.com")
    assert anonymous_client.get("/api/admin/overview", headers=workspace_admin).status_code == 403
    admin_id = promote("workspace-admin@example.com")
    overview = anonymous_client.get("/api/admin/overview", headers=workspace_admin)
    assert overview.status_code == 200 and overview.json()["metrics"]["total_users"] >= 1
    users = anonymous_client.get("/api/admin/users?limit=1&offset=0", headers=workspace_admin).json()
    assert users["limit"] == 1 and users["total"] >= 1 and len(users["items"]) == 1
    assert "password_hash" not in users["items"][0] and "token" not in users["items"][0]
    detail = anonymous_client.get(f"/api/admin/users/{admin_id}", headers=workspace_admin).json()
    assert "password_hash" not in str(detail) and "storage_key" not in str(detail) and "result_summary" not in str(detail)


def test_user_actions_are_audited_and_protect_self_and_last_admin(anonymous_client) -> None:
    _, headers = register(anonymous_client, "platform-admin@example.com"); admin_id = promote("platform-admin@example.com")
    _, target_headers = register(anonymous_client, "target-user@example.com"); target_id = anonymous_client.get("/api/auth/me", headers=target_headers).json()["user"]["id"]
    missing_confirmation = anonymous_client.post(f"/api/admin/users/{target_id}/actions", headers=headers, json={"action": "deactivate", "confirmed": False})
    assert missing_confirmation.status_code == 400
    changed = anonymous_client.post(f"/api/admin/users/{target_id}/actions", headers=headers, json={"action": "deactivate", "confirmed": True})
    assert changed.status_code == 200 and changed.json()["active"] is False
    assert anonymous_client.post(f"/api/admin/users/{admin_id}/actions", headers=headers, json={"action": "revoke_admin", "confirmed": True}).status_code == 409
    audit = anonymous_client.get("/api/admin/audit", headers=headers).json()
    assert audit["total"] >= 1 and audit["items"][0]["action"] == "user_deactivate"


def test_workspace_usage_jobs_errors_storage_and_provider_metadata(anonymous_client) -> None:
    _, headers = register(anonymous_client, "ops-admin@example.com"); promote("ops-admin@example.com")
    workspace_id = headers["X-Workspace-ID"]
    from app.core.database import session_scope
    with session_scope() as session:
        session.add(Job(workspace_id=workspace_id, user_id=None, type="report", status="failed", stage="failed", retryable=True, payload={"title": "Test", "format": "html"})); session.commit()
    assert anonymous_client.get("/api/admin/workspaces?limit=1", headers=headers).json()["items"][0]["id"] == workspace_id
    assert anonymous_client.get(f"/api/admin/workspaces/{workspace_id}", headers=headers).json()["datasets"] == []
    assert anonymous_client.get("/api/admin/usage?days=7", headers=headers).status_code == 200
    assert anonymous_client.get("/api/admin/jobs?status=failed", headers=headers).json()["total"] == 1
    anonymous_client.get("/api/admin/overview", headers={})
    errors = anonymous_client.get("/api/admin/errors", headers=headers).json()
    assert errors["total"] >= 1 and "safe_message" in errors["items"][0]
    storage = anonymous_client.get("/api/admin/storage", headers=headers).json()
    assert "dataset_bytes" in storage and "root" not in storage and "path" not in storage
    providers = anonymous_client.get("/api/admin/providers", headers=headers).json()
    assert "password" not in str(providers).lower() and "api_key" not in str(providers).lower()


def test_feedback_filters_workflow_support_and_business_are_safe(anonymous_client) -> None:
    _, headers = register(anonymous_client, "support-admin@example.com"); promote("support-admin@example.com")
    created = anonymous_client.post("/api/feedback", headers=headers, json={"category": "bug", "message": "Admin workflow test"}).json()
    filtered = anonymous_client.get("/api/admin/feedback?category=bug&status=new&limit=5", headers=headers).json()
    assert filtered["total"] == 1 and filtered["items"][0]["priority"] == "medium"
    updated = anonymous_client.patch(f"/api/admin/feedback/{created['id']}", headers=headers, json={"status": "reviewing", "priority": "high"})
    assert updated.status_code == 200 and updated.json()["priority"] == "high"
    support = anonymous_client.get("/api/admin/support?q=support-admin", headers=headers)
    assert support.status_code == 200 and support.json()["results"]
    audit = anonymous_client.get("/api/admin/audit", headers=headers).json()["items"]
    assert {item["action"] for item in audit} >= {"feedback_status_change", "support_lookup"}
    business = anonymous_client.get("/api/admin/business", headers=headers).json()
    assert business["revenue_available"] is False and business["estimated_cost"] is None and "unavailable" in business["revenue_message"].lower()


def test_cli_promotion_and_last_admin_protection(anonymous_client) -> None:
    register(anonymous_client, "cli-primary@example.com"); promote("cli-primary@example.com")
    register(anonymous_client, "cli-secondary@example.com")
    from app.cli import set_system_admin
    assert set_system_admin("cli-secondary@example.com", True) == 0
    assert set_system_admin("cli-secondary@example.com", False) == 0
    assert set_system_admin("cli-primary@example.com", False) == 2
