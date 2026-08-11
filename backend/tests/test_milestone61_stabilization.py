import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models import User, WorkspaceInvitation
from app.services.email import SMTPEmailProvider, email_delivery_diagnostics, send_transactional_email


def register(client, email: str) -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPass123", "display_name": "Beta Tester", "beta_acknowledged": True})
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}", "X-Workspace-ID": body["workspaces"][0]["id"]}


def token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def verify_from_registration(client, payload: dict) -> None:
    assert payload["development_verification_url"]
    assert client.post("/api/auth/verify-email", json={"token": token_from_url(payload["development_verification_url"])}).status_code == 200


def test_console_verification_links_are_development_only(anonymous_client) -> None:
    from app.core.config import get_settings

    os.environ["EMAIL_PROVIDER"] = "console"; os.environ["APP_ENV"] = "development"; get_settings.cache_clear()
    payload, headers = register(anonymous_client, "dev-link@example.com")
    assert payload["email_delivery_status"] == "success"
    assert payload["development_verification_url"].startswith("http://localhost:3000/verify-email?token=")
    resent = anonymous_client.post("/api/auth/resend-verification", headers=headers).json()
    assert resent["development_verification_url"] and resent["development_verification_url"] != payload["development_verification_url"]

    os.environ["APP_ENV"] = "production"; get_settings.cache_clear()
    try:
        production, _ = register(anonymous_client, "no-link@example.com")
        assert production["development_verification_url"] is None
    finally:
        os.environ["APP_ENV"] = "development"; get_settings.cache_clear()


def test_invitation_link_visibility_resend_expiry_and_acceptance(anonymous_client) -> None:
    from app.core.config import get_settings
    from app.core.database import session_scope

    os.environ["EMAIL_PROVIDER"] = "console"; os.environ["APP_ENV"] = "development"; get_settings.cache_clear()
    owner_payload, owner = register(anonymous_client, "invite-owner@example.com"); verify_from_registration(anonymous_client, owner_payload)
    workspace_id = owner["X-Workspace-ID"]
    created = anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=owner, json={"email": "invited@example.com", "role": "member"})
    assert created.status_code == 201, created.text
    original_url = created.json()["development_invitation_url"]
    assert original_url and created.json()["status"] == "pending"

    resent = anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations/{created.json()['id']}/resend", headers=owner)
    assert resent.status_code == 200, resent.text
    replacement_url = resent.json()["development_invitation_url"]
    assert replacement_url and replacement_url != original_url

    _, invited = register(anonymous_client, "invited@example.com")
    assert anonymous_client.post(f"/api/invitations/{token_from_url(original_url)}/accept", headers=invited).status_code == 400
    accepted = anonymous_client.post(f"/api/invitations/{token_from_url(replacement_url)}/accept", headers=invited)
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"

    late = anonymous_client.post(f"/api/workspaces/{workspace_id}/invitations", headers=owner, json={"email": "late-status@example.com", "role": "admin"})
    with session_scope() as session:
        item = session.get(WorkspaceInvitation, late.json()["id"]); item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); session.commit()
    listed = anonymous_client.get(f"/api/workspaces/{workspace_id}/invitations", headers=owner).json()
    assert next(item for item in listed if item["id"] == late.json()["id"])["status"] == "expired"


def test_smtp_mode_never_returns_plaintext_invitation_token(anonymous_client, monkeypatch) -> None:
    from app.core.config import get_settings

    os.environ["EMAIL_PROVIDER"] = "console"; os.environ["APP_ENV"] = "development"; get_settings.cache_clear()
    owner_payload, owner = register(anonymous_client, "smtp-owner@example.com"); verify_from_registration(anonymous_client, owner_payload)
    async def accepted(self, recipient: str, subject: str, text: str) -> None: return None
    monkeypatch.setattr(SMTPEmailProvider, "send_email", accepted)
    os.environ["EMAIL_PROVIDER"] = "smtp"; os.environ["SMTP_HOST"] = "smtp.example.com"; get_settings.cache_clear()
    try:
        response = anonymous_client.post(f"/api/workspaces/{owner['X-Workspace-ID']}/invitations", headers=owner, json={"email": "smtp-target@example.com", "role": "member"})
        assert response.status_code == 201, response.text
        assert response.json()["development_invitation_url"] is None
        assert "token=" not in response.text
    finally:
        os.environ["EMAIL_PROVIDER"] = "console"; os.environ.pop("SMTP_HOST", None); get_settings.cache_clear()


def test_failed_email_provider_returns_safe_error_and_diagnostic(anonymous_client, monkeypatch) -> None:
    from app.core.config import get_settings

    os.environ["EMAIL_PROVIDER"] = "console"; os.environ["APP_ENV"] = "development"; get_settings.cache_clear()
    owner_payload, owner = register(anonymous_client, "failure-owner@example.com"); verify_from_registration(anonymous_client, owner_payload)
    async def failed(self, recipient: str, subject: str, text: str) -> None:
        raise AppError("The email provider could not accept this message. Please try again.", "EMAIL_DELIVERY_FAILED", 503)
    monkeypatch.setattr(SMTPEmailProvider, "send_email", failed)
    os.environ["EMAIL_PROVIDER"] = "smtp"; os.environ["SMTP_HOST"] = "smtp.example.com"; get_settings.cache_clear()
    try:
        response = anonymous_client.post(f"/api/workspaces/{owner['X-Workspace-ID']}/invitations", headers=owner, json={"email": "failure-target@example.com", "role": "member"})
        assert response.status_code == 503 and response.json()["error_code"] == "EMAIL_DELIVERY_FAILED"
        diagnostic = email_delivery_diagnostics()
        assert diagnostic["status"] == "failed" and diagnostic["operation"] == "workspace_invitation"
    finally:
        os.environ["EMAIL_PROVIDER"] = "console"; os.environ.pop("SMTP_HOST", None); get_settings.cache_clear()


@pytest.mark.parametrize("failure_kind, expected_classification", [("connection", "connection"), ("timeout", "timeout"), ("authentication", "authentication")])
def test_smtp_failure_classes_are_safe(monkeypatch, caplog, failure_kind: str, expected_classification: str) -> None:
    import asyncio
    import smtplib

    from app.core.config import get_settings

    secret = "smtp-password-must-not-be-logged"

    class AuthenticationFailureClient:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def starttls(self): return None
        def login(self, _username, _password): raise smtplib.SMTPAuthenticationError(535, b"authentication rejected")
        def send_message(self, _message): return None

    def smtp_factory(*_args, **_kwargs):
        if failure_kind == "connection": raise OSError("connection refused")
        if failure_kind == "timeout": raise TimeoutError("connection timed out")
        return AuthenticationFailureClient()

    monkeypatch.setattr(smtplib, "SMTP", smtp_factory)
    os.environ.update({"EMAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_USERNAME": "beta-user", "SMTP_PASSWORD": secret})
    get_settings.cache_clear()
    caplog.set_level("ERROR")
    try:
        with pytest.raises(AppError) as caught:
            asyncio.run(send_transactional_email("recipient@example.com", "Beta message", "Safe message", "smtp_failure_test"))
        assert caught.value.error_code == "EMAIL_DELIVERY_FAILED"
        assert email_delivery_diagnostics()["classification"] == expected_classification
        assert secret not in caplog.text and "recipient@example.com" not in caplog.text
    finally:
        for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"): os.environ.pop(key, None)
        os.environ["EMAIL_PROVIDER"] = "console"; get_settings.cache_clear()


def test_feedback_attachment_validation_storage_and_admin_download(anonymous_client) -> None:
    from app.core.database import session_scope

    _, first = register(anonymous_client, "attachment-a@example.com")
    _, second = register(anonymous_client, "attachment-b@example.com")
    feedback = anonymous_client.post("/api/feedback", headers=first, json={"category": "bug", "message": "Screenshot attached", "include_technical_context": True}).json()
    invalid = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=first, files=[("files", ("payload.html", b"<script>alert(1)</script>", "text/html"))])
    assert invalid.status_code == 400 and invalid.json()["error_code"] == "FEEDBACK_ATTACHMENT_TYPE_INVALID"
    disguised = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=first, files=[("files", ("fake.png", b"not a png", "image/png"))])
    assert disguised.status_code == 400 and disguised.json()["error_code"] == "FEEDBACK_ATTACHMENT_CONTENT_INVALID"
    cross_tenant = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=second, files=[("files", ("shot.png", b"\x89PNG\r\n\x1a\nimage", "image/png"))])
    assert cross_tenant.status_code == 404
    created = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=first, files=[("files", ("error screenshot.png", b"\x89PNG\r\n\x1a\nimage", "image/png"))])
    assert created.status_code == 201, created.text
    attachment = created.json()[0]
    assert "storage_key" not in attachment and attachment["original_filename"] == "error screenshot.png"

    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == "attachment-a@example.com")); user.is_system_admin = True; session.commit()
    items = anonymous_client.get("/api/admin/feedback", headers=first).json()
    found = next(item for item in items if item["id"] == feedback["id"])
    assert found["user_email"] == "attachment-a@example.com" and found["attachments"][0]["id"] == attachment["id"]
    downloaded = anonymous_client.get(f"/api/admin/feedback/{feedback['id']}/attachments/{attachment['id']}", headers=first)
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"\x89PNG")


def test_feedback_attachment_size_and_count_limits(anonymous_client) -> None:
    from app.core.config import get_settings

    _, headers = register(anonymous_client, "attachment-limits@example.com")
    feedback = anonymous_client.post("/api/feedback", headers=headers, json={"category": "bug", "message": "Limits"}).json()
    os.environ["FEEDBACK_MAX_ATTACHMENT_MB"] = "1"; os.environ["FEEDBACK_MAX_ATTACHMENTS"] = "2"; get_settings.cache_clear()
    try:
        oversized = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=headers, files=[("files", ("large.txt", b"a" * (1024 * 1024 + 1), "text/plain"))])
        assert oversized.status_code == 413
        too_many = anonymous_client.post(f"/api/feedback/{feedback['id']}/attachments", headers=headers, files=[("files", (f"{index}.txt", b"safe", "text/plain")) for index in range(3)])
        assert too_many.status_code == 400 and too_many.json()["error_code"] == "FEEDBACK_ATTACHMENT_COUNT_INVALID"
    finally:
        os.environ.pop("FEEDBACK_MAX_ATTACHMENT_MB", None); os.environ.pop("FEEDBACK_MAX_ATTACHMENTS", None); get_settings.cache_clear()
