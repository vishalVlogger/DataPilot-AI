import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
import pytest

from app.core.observability import initialize_sentry
from app.core.rate_limit import RedisRateLimiter
from app.core.security import hash_one_time_token
from app.models import AccountToken, User
from app.repositories import JobRepository
from app.services.cleanup import CleanupService
from app.services.datasets.storage import LocalDatasetStorage, get_dataset_storage
from app.services.email import console_outbox
from app.services.features import feature_flags
from app.services.jobs.executor import LocalJobExecutor, get_job_executor


def register(client, email: str, name: str = "Beta User") -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPass123", "display_name": name, "beta_acknowledged": True})
    assert response.status_code == 201, response.text
    payload = response.json()
    return payload, {"Authorization": f"Bearer {payload['access_token']}", "X-Workspace-ID": payload["workspaces"][0]["id"]}


def email_token(subject: str, email: str) -> str:
    message = next(item for item in reversed(console_outbox) if item["recipient"] == email and subject in item["subject"])
    return re.search(r"token=([^\s]+)", message["text"]).group(1)


def verify(client, email: str, headers: dict[str, str]) -> None:
    token = email_token("Verify", email)
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.get("/api/auth/me", headers=headers).json()["user"]["email_verified_at"]


def test_verification_expiry_reuse_and_resend(anonymous_client) -> None:
    console_outbox.clear(); payload, headers = register(anonymous_client, "verify@example.com")
    token = email_token("Verify", "verify@example.com")
    first = anonymous_client.post("/api/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert anonymous_client.post("/api/auth/verify-email", json={"token": token}).status_code == 400
    before = len(console_outbox)
    assert anonymous_client.post("/api/auth/resend-verification", headers=headers).status_code == 200
    assert len(console_outbox) == before

    _, _ = register(anonymous_client, "expired-verify@example.com")
    expired = email_token("Verify", "expired-verify@example.com")
    from app.core.database import session_scope
    with session_scope() as session:
        item = session.scalar(select(AccountToken).where(AccountToken.token_hash == hash_one_time_token(expired)))
        item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); session.commit()
    assert anonymous_client.post("/api/auth/verify-email", json={"token": expired}).status_code == 400


def test_password_reset_is_generic_one_time_and_revokes_sessions(anonymous_client) -> None:
    console_outbox.clear(); _, _ = register(anonymous_client, "reset@example.com")
    generic = anonymous_client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    found = anonymous_client.post("/api/auth/forgot-password", json={"email": "reset@example.com"})
    assert generic.status_code == found.status_code == 200 and generic.json() == found.json()
    token = email_token("Reset", "reset@example.com")
    reset = anonymous_client.post("/api/auth/reset-password", json={"token": token, "new_password": "Replacement123"})
    assert reset.status_code == 200
    assert anonymous_client.post("/api/auth/reset-password", json={"token": token, "new_password": "AnotherPass123"}).status_code == 400
    assert anonymous_client.post("/api/auth/refresh").status_code == 401
    assert anonymous_client.post("/api/auth/login", json={"email": "reset@example.com", "password": "Replacement123"}).status_code == 200


def test_reset_token_expiry(anonymous_client) -> None:
    console_outbox.clear(); register(anonymous_client, "expired-reset@example.com")
    anonymous_client.post("/api/auth/forgot-password", json={"email": "expired-reset@example.com"})
    token = email_token("Reset", "expired-reset@example.com")
    from app.core.database import session_scope
    with session_scope() as session:
        item = session.scalar(select(AccountToken).where(AccountToken.token_hash == hash_one_time_token(token)))
        item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); session.commit()
    assert anonymous_client.post("/api/auth/reset-password", json={"token": token, "new_password": "Replacement123"}).status_code == 400


def test_invitation_acceptance_duplicate_expiry_and_member_security(anonymous_client) -> None:
    console_outbox.clear(); _, owner = register(anonymous_client, "owner@example.com", "Owner"); verify(anonymous_client, "owner@example.com", owner)
    workspace_id = owner["X-Workspace-ID"]
    created = anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=owner, json={"email": "member@example.com", "role": "member"})
    assert created.status_code == 201, created.text
    assert anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=owner, json={"email": "member@example.com", "role": "member"}).status_code == 409
    invite_token = email_token("invitation", "member@example.com")
    _, member = register(anonymous_client, "member@example.com", "Member")
    accepted = anonymous_client.post(f"/api/invitations/{invite_token}/accept", headers=member)
    assert accepted.status_code == 200
    member_in_owner_workspace = {**member, "X-Workspace-ID": workspace_id}
    members = anonymous_client.get(f"/api/workspaces/{workspace_id}/members", headers=member_in_owner_workspace)
    assert members.status_code == 200
    assert any(item["email"] == "member@example.com" and item["role"] == "member" for item in members.json())
    assert anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=member_in_owner_workspace, json={"email": "other@example.com", "role": "member"}).status_code == 403
    assert anonymous_client.patch(f"/api/workspaces/{workspace_id}/members/{accepted.json()['invited_by_user_id']}", headers=owner, json={"role": "member"}).status_code == 409
    assert anonymous_client.delete(f"/api/workspaces/{workspace_id}/members/{accepted.json()['invited_by_user_id']}", headers=owner).status_code == 409

    expiring = anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=owner, json={"email": "late@example.com", "role": "member"})
    token = email_token("invitation", "late@example.com")
    from app.core.database import session_scope
    from app.models import WorkspaceInvitation
    with session_scope() as session:
        invitation = session.get(WorkspaceInvitation, expiring.json()["id"]); invitation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); session.commit()
    assert anonymous_client.post(f"/api/invitations/{token}/accept", headers=member).status_code == 400


def test_feedback_tenant_scope_and_system_admin_tools(anonymous_client) -> None:
    _, first = register(anonymous_client, "feedback-a@example.com")
    _, second = register(anonymous_client, "feedback-b@example.com")
    uploaded = anonymous_client.post("/api/datasets/upload", headers=second, files={"file": ("b.csv", b"Name,Sales\nB,1\n", "text/csv")}).json()
    forbidden = anonymous_client.post("/api/feedback", headers=first, json={"category": "bug", "message": "Cross tenant", "dataset_id": uploaded["id"]})
    assert forbidden.status_code == 404
    created = anonymous_client.post("/api/feedback", headers=first, json={"category": "confusing_result", "message": "Needs explanation", "include_technical_context": True, "request_id": "beta-ref"})
    assert created.status_code == 201
    assert anonymous_client.get("/api/admin/summary", headers=first).status_code == 403
    from app.core.database import session_scope
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == "feedback-a@example.com")); user.is_system_admin = True; session.commit()
    assert anonymous_client.get("/api/admin/summary", headers=first).status_code == 200
    assert anonymous_client.get("/api/admin/feedback", headers=first).json()[0]["message"] == "Needs explanation"
    support = anonymous_client.get("/api/admin/support?q=feedback-a", headers=first).json()["results"]
    assert support and support[0]["type"] == "user" and "password_hash" not in support[0]


def test_request_id_generation_and_propagation(anonymous_client) -> None:
    generated = anonymous_client.get("/api/health")
    assert generated.headers["X-Request-ID"]
    supplied = anonymous_client.get("/api/health", headers={"X-Request-ID": "beta-reference-123"})
    assert supplied.headers["X-Request-ID"] == "beta-reference-123"
    error = anonymous_client.get("/api/auth/me", headers={"X-Request-ID": "error-reference"})
    assert error.json()["request_id"] == "error-reference"


def test_cleanup_feature_flags_and_local_infrastructure(client, tmp_path) -> None:
    from app.core.config import get_settings
    from app.core.database import session_scope
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == "existing-tests@example.com"))
        session.add(AccountToken(user_id=user.id, purpose="verify_email", token_hash="f" * 64, expires_at=datetime.now(timezone.utc) - timedelta(days=1))); session.commit()
    result = CleanupService().run()
    assert result["account_tokens"] >= 1
    assert feature_flags.enabled("workspace_invites") is True
    assert isinstance(get_dataset_storage(get_settings().storage_root, workspace_id=get_settings().legacy_workspace_id), LocalDatasetStorage)
    assert isinstance(get_job_executor(), LocalJobExecutor)
    assert initialize_sentry(None, "test") is False


def test_invite_only_registration_mode(anonymous_client) -> None:
    from app.core.config import get_settings
    os.environ["REGISTRATION_MODE"] = "invite_only"; get_settings.cache_clear()
    try:
        response = anonymous_client.post("/api/auth/register", json={"email": "closed@example.com", "password": "StrongPass123", "display_name": "Closed"})
        assert response.status_code == 403 and response.json()["error_code"] == "INVITATION_REQUIRED"
    finally:
        os.environ["REGISTRATION_MODE"] = "open"; get_settings.cache_clear()


def test_job_retry_guardrails_and_external_ai_policy(client) -> None:
    from app.core.database import session_scope

    workspace_id = client.headers["X-Workspace-ID"]
    with session_scope() as session:
        non_retryable = JobRepository(session, workspace_id).create("profile", None, "failed", retryable=False)
        unfinished = JobRepository(session, workspace_id).create("report", None, "running", retryable=True, payload={"format": "html"})

    first = client.post(f"/api/jobs/{non_retryable['id']}/retry")
    second = client.post(f"/api/jobs/{unfinished['id']}/retry")
    assert first.status_code == second.status_code == 409
    assert first.json()["error_code"] == second.json()["error_code"] == "JOB_NOT_RETRYABLE"

    provider = client.get("/api/ai/provider-status")
    assert provider.status_code == 200
    body = provider.json()
    assert body["email_verified"] is False
    assert body["external_ai_allowed"] is False
    assert body["effective_provider"] == "mock"


def test_redis_rate_limiter_uses_bounded_counter() -> None:
    class FakePipeline:
        def __init__(self) -> None: self.count = 0; self.expiration = None
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def incr(self, _key): self.count += 1; return self
        def expire(self, _key, seconds, nx=False): self.expiration = (seconds, nx); return self
        def execute(self): return [self.count, True]

    pipeline = FakePipeline()
    limiter = RedisRateLimiter.__new__(RedisRateLimiter)
    limiter.client = type("FakeRedis", (), {"pipeline": lambda self: pipeline})()
    limiter.check("login:test", 1, 45)
    assert pipeline.expiration == (45, True)
    from app.core.errors import AppError
    with pytest.raises(AppError) as raised: limiter.check("login:test", 1, 45)
    assert raised.value.error_code == "RATE_LIMITED"
