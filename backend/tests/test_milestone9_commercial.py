from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Dataset, Subscription, SystemAdminAudit, UpgradeRequest, UsageEvent, User, Workspace
from app.services.commercial import DEFAULT_PLANS, EntitlementService, PlanDefinition, billing_period


def register(client, email: str) -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"email": email, "password": "Commercial123", "display_name": "Commercial User", "beta_acknowledged": True})
    assert response.status_code == 201, response.text
    body = response.json(); return body, {"Authorization": f"Bearer {body['access_token']}", "X-Workspace-ID": body["workspaces"][0]["id"]}


def promote(email: str) -> None:
    from app.core.database import session_scope
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == email)); user.is_system_admin = True; session.commit()


def test_public_catalog_prices_are_safe_and_centralized(anonymous_client) -> None:
    response = anonymous_client.get("/api/plans")
    assert response.status_code == 200
    body = response.json(); assert [item["code"] for item in body["plans"]] == ["free", "pro", "business"]
    assert body["plans"][0]["price"]["monthly"] == 0
    assert body["plans"][1]["price"]["configured"] is False and body["payments_enabled"] is False
    assert body["plans"][0]["limits"]["datasets"] == 5 and body["plans"][1]["limits"]["datasets"] == 50
    assert body["plans"][2]["limits"]["workspace_members"] == 50 and "priority_jobs" in body["plans"][2]["features"]
    assert "provider" not in str(body["plans"]).casefold()


def test_trial_is_one_per_workspace_expires_to_base_without_deleting_data(anonymous_client) -> None:
    _, headers = register(anonymous_client, "trial-owner@example.com"); workspace_id = headers["X-Workspace-ID"]
    started = anonymous_client.post(f"/api/workspaces/{workspace_id}/trial/start", headers=headers)
    assert started.status_code == 201 and started.json()["effective_plan"] == "pro"
    state = anonymous_client.get(f"/api/workspaces/{workspace_id}/subscription", headers=headers).json()
    assert state["plan_source"] == "trial" and state["trial"]["eligible"] is False and state["effective_plan"]["code"] == "pro"
    assert anonymous_client.get("/api/ai/provider-status", headers=headers).json()["external_ai_plan_entitled"] is True
    assert anonymous_client.post(f"/api/workspaces/{workspace_id}/trial/start", headers=headers).status_code == 409
    from app.core.database import session_scope
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id); workspace.trial_ends_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.add(Dataset(id="trial-dataset", workspace_id=workspace_id, uploader_user_id=workspace.owner_user_id, name="kept.csv", original_filename="kept.csv", source_type="csv", row_count=1, column_count=1, storage_key="kept", storage_bytes=1)); session.commit()
    expired = anonymous_client.get(f"/api/workspaces/{workspace_id}/subscription", headers=headers).json()
    assert expired["effective_plan"]["code"] == "free" and expired["trial"]["status"] == "expired"
    with session_scope() as session: assert session.get(Dataset, "trial-dataset") is not None


def test_usage_meter_is_idempotent_and_calendar_month_scoped(anonymous_client) -> None:
    _, headers = register(anonymous_client, "meter@example.com"); workspace_id = headers["X-Workspace-ID"]; service = EntitlementService(workspace_id)
    assert service.record("analysis", 1, None, meter_key="analysis:stable") is True
    assert service.record("analysis", 1, None, meter_key="analysis:stable") is False
    assert service.summary()["analyses_this_month"] == 1
    from app.core.database import session_scope
    with session_scope() as session:
        old = UsageEvent(workspace_id=workspace_id, event_type="analysis", quantity=9, meter_key="analysis:old", created_at=billing_period()[0] - timedelta(days=1)); session.add(old); session.commit()
    assert EntitlementService(workspace_id).summary()["analyses_this_month"] == 1
    failed_report = anonymous_client.post("/api/datasets/missing/report", headers=headers, json={"title": "Missing", "format": "html"})
    assert failed_report.status_code == 404 and EntitlementService(workspace_id).summary()["reports_this_month"] == 0


def test_structured_plan_limit_and_warning_thresholds(anonymous_client, monkeypatch) -> None:
    _, headers = register(anonymous_client, "limits@example.com"); workspace_id = headers["X-Workspace-ID"]
    plan = PlanDefinition(1, 100 * 1024 * 1024, 1024 * 1024, 100, 10, 1, 0); monkeypatch.setitem(DEFAULT_PLANS, "free", plan)
    service = EntitlementService(workspace_id)
    for index in range(8): service.record("analysis", 1, None, meter_key=f"near:{index}")
    assert service.summary()["usage"]["analyses_per_month"]["level"] == "warning"
    service.record("analysis", 1, None, meter_key="critical")
    assert service.summary()["usage"]["analyses_per_month"]["level"] == "critical"
    service.record("analysis", 1, None, meter_key="limit")
    assert service.summary()["usage"]["analyses_per_month"]["level"] == "limit"
    response = anonymous_client.post("/api/datasets/upload", headers=headers, files={"file": ("one.csv", b"x\n1\n", "text/csv")})
    assert response.status_code == 201
    blocked = anonymous_client.post("/api/datasets/upload", headers=headers, files={"file": ("two.csv", b"x\n2\n", "text/csv")})
    body = blocked.json(); assert body["code"] == "PLAN_LIMIT_REACHED" and body["resource"] == "datasets" and body["upgrade_recommended"] is True


def test_upgrade_request_security_and_manual_assignment_are_audited(anonymous_client) -> None:
    _, owner = register(anonymous_client, "upgrade-owner@example.com"); workspace_id = owner["X-Workspace-ID"]
    requested = anonymous_client.post(f"/api/workspaces/{workspace_id}/upgrade-request", headers=owner, json={"requested_plan": "business", "message": "Team rollout"})
    assert requested.status_code == 201
    assert anonymous_client.post(f"/api/workspaces/{workspace_id}/upgrade-request", headers=owner, json={"requested_plan": "pro"}).status_code == 409
    assert anonymous_client.post(f"/api/admin/commercial/workspaces/{workspace_id}/manual-plan", headers=owner, json={"plan_code": "business", "confirmed": True}).status_code == 403
    _, admin = register(anonymous_client, "commercial-admin@example.com"); promote("commercial-admin@example.com")
    assigned = anonymous_client.post(f"/api/admin/commercial/workspaces/{workspace_id}/manual-plan", headers=admin, json={"plan_code": "business", "confirmed": True})
    assert assigned.status_code == 200 and assigned.json()["effective_plan"] == "business" and assigned.json()["revenue_recorded"] is False
    request_id = requested.json()["id"]
    assert anonymous_client.post(f"/api/admin/commercial/upgrade-requests/{request_id}/status", headers=admin, json={"status": "approved"}).status_code == 200
    summary = anonymous_client.get("/api/admin/commercial/summary", headers=admin).json()
    assert summary["manual_subscriptions"] == 1 and summary["revenue_available"] is False and summary["profit_available"] is False
    from app.core.database import session_scope
    with session_scope() as session:
        subscription = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id)); assert subscription.plan_code == "business" and subscription.billing_provider == "manual"
        assert session.scalar(select(UpgradeRequest).where(UpgradeRequest.id == request_id)).status == "approved"
        actions = set(session.scalars(select(SystemAdminAudit.action)).all()); assert {"manual_plan_assigned", "commercial_request_status_changed"} <= actions


def test_cross_workspace_subscription_access_is_blocked(anonymous_client) -> None:
    _, first = register(anonymous_client, "first-commercial@example.com"); _, second = register(anonymous_client, "second-commercial@example.com")
    assert anonymous_client.get(f"/api/workspaces/{first['X-Workspace-ID']}/subscription", headers=second).status_code == 404
    assert anonymous_client.post(f"/api/workspaces/{first['X-Workspace-ID']}/trial/start", headers=second).status_code == 404
