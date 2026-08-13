from contextlib import contextmanager

from sqlalchemy import select

from app.core.database import session_scope
from app.models import ProductEvent, SystemAdminAudit, User
from app.services.product_analytics import ProductEvents, record_product_event


def _activate_admin_and_verify() -> str:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == "existing-tests@example.com"))
        user.is_system_admin = True
        from datetime import datetime, timezone
        user.email_verified_at = datetime.now(timezone.utc)
        session.commit()
        return user.id


def test_event_taxonomy_allowlists_metadata_and_is_failure_isolated(client, monkeypatch) -> None:
    me = client.get("/api/auth/me").json(); user_id = me["user"]["id"]; workspace_id = me["workspaces"][0]["id"]
    assert record_product_event(ProductEvents.CHART_CREATED, user_id, workspace_id, properties={"chart_type": "bar", "question": "private prompt", "rows": ["private"]})
    with session_scope() as session:
        event = session.scalar(select(ProductEvent).where(ProductEvent.user_id == user_id, ProductEvent.event_name == ProductEvents.CHART_CREATED).order_by(ProductEvent.occurred_at.desc()))
        assert event.properties == {"chart_type": "bar"}

    @contextmanager
    def broken_scope():
        raise RuntimeError("analytics database unavailable")
        yield

    monkeypatch.setattr("app.services.product_analytics.session_scope", broken_scope)
    assert record_product_event(ProductEvents.LOGGED_IN, user_id) is False


def test_sample_onboarding_analysis_feedback_and_quota_exclusion(client) -> None:
    _activate_admin_and_verify()
    sample = client.post("/api/onboarding/sample-dataset")
    assert sample.status_code == 201, sample.text
    assert sample.json()["is_sample"] is True
    assert client.post("/api/onboarding/sample-dataset").json()["id"] == sample.json()["id"]
    usage = client.get("/api/usage").json()
    assert usage["datasets"] == 0 and usage["storage_bytes"] == 0

    examples = client.get("/api/onboarding/question-examples", params={"dataset_id": sample.json()["id"]})
    assert examples.status_code == 200 and any("Revenue" in item and "Region" in item for item in examples.json()["examples"])
    answer = client.post(f"/api/datasets/{sample.json()['id']}/ask", json={"question": "Show total Revenue by Region"})
    assert answer.status_code == 200, answer.text
    run_id = answer.json()["metadata"]["run_id"]
    rated = client.put(f"/api/analysis-runs/{run_id}/feedback", json={"helpful": True, "comment": "Useful summary"})
    assert rated.status_code == 200 and rated.json()["helpful"] is True
    assert client.put("/api/analysis-runs/00000000-0000-0000-0000-000000000000/feedback", json={"helpful": True}).status_code == 404

    progress = client.get("/api/onboarding").json()
    completed = {item["key"]: item["complete"] for item in progress["steps"]}
    assert completed["verify"] and completed["upload"] and completed["analyze"]


def test_admin_product_dashboard_status_notes_and_audit(client) -> None:
    user_id = _activate_admin_and_verify()
    dashboard = client.get("/api/admin/product", params={"range": "30"})
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["summary"]["signups"] >= 1
    assert [item["step"] for item in body["funnel"]] == ["registered", "verified", "first_login", "first_upload", "first_analysis", "chart_or_insight", "report_or_export", "returned"]
    assert "d1" in body["retention"] and "users" in body

    changed = client.patch(f"/api/admin/product/users/{user_id}/status", json={"status": "needs_follow_up"})
    assert changed.status_code == 200 and changed.json()["beta_status"] == "needs_follow_up"
    note = client.post(f"/api/admin/product/users/{user_id}/notes", json={"note": "Invite to the next beta interview."})
    assert note.status_code == 201
    assert client.get(f"/api/admin/product/users/{user_id}/notes").json()[0]["note"].startswith("Invite")
    with session_scope() as session:
        actions = set(session.scalars(select(SystemAdminAudit.action)).all())
        assert {"beta_status_change", "beta_note_added"}.issubset(actions)


def test_structured_feedback_fields_are_persisted(client) -> None:
    created = client.post("/api/feedback", json={"category": "bug", "message": "Chart labels overlap", "feature_area": "charts", "severity": "high", "affected_flow": "first chart", "include_technical_context": False})
    assert created.status_code == 201, created.text
    assert created.json()["feature_area"] == "charts"
    assert created.json()["severity"] == "high"
    assert created.json()["affected_flow"] == "first chart"


def test_three_user_beta_simulation_reports_activation_and_follow_up(anonymous_client) -> None:
    users = []
    for index in range(3):
        response = anonymous_client.post("/api/auth/register", json={"email": f"beta-{index}@example.com", "password": "StrongPass123", "display_name": f"Beta {index}", "beta_acknowledged": True})
        payload = response.json(); users.append((payload["user"]["id"], {"Authorization": f"Bearer {payload['access_token']}", "X-Workspace-ID": payload["workspaces"][0]["id"]}))
    with session_scope() as session:
        from datetime import datetime, timezone
        for user_id, _ in users[:2]: session.get(User, user_id).email_verified_at = datetime.now(timezone.utc)
        session.get(User, users[0][0]).is_system_admin = True; session.commit()
    for _, headers in users[:2]:
        sample = anonymous_client.post("/api/onboarding/sample-dataset", headers=headers).json()
        assert anonymous_client.post(f"/api/datasets/{sample['id']}/ask", headers=headers, json={"question": "Show total Revenue by Region"}).status_code == 200
    assert anonymous_client.post("/api/feedback", headers=users[2][1], json={"category": "general", "message": "I need help starting", "feature_area": "onboarding", "severity": "medium", "affected_flow": "first dataset"}).status_code == 201
    dashboard = anonymous_client.get("/api/admin/product", headers=users[0][1], params={"range": "all"}).json()
    assert dashboard["summary"]["signups"] >= 3
    assert dashboard["summary"]["activated"] >= 2
    follow_up = {item["email"]: item["recommended_follow_up"] for item in dashboard["users"]}
    assert follow_up["beta-2@example.com"] == "Verify email"
