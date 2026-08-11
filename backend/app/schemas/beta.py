from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: Literal["admin", "member"] = "member"


class InvitationResponse(BaseModel):
    id: str; workspace_id: str; email: EmailStr; role: Literal["admin", "member"]; invited_by_user_id: str; created_at: datetime; expires_at: datetime; accepted_at: datetime | None; revoked_at: datetime | None
    status: Literal["pending", "accepted", "expired", "revoked"] = "pending"
    delivery_status: Literal["success", "failed"] | None = None
    development_invitation_url: str | None = None


class MemberResponse(BaseModel):
    user_id: str; email: EmailStr; display_name: str; role: Literal["owner", "admin", "member"]; joined_at: datetime


class MemberRoleRequest(BaseModel):
    role: Literal["admin", "member"]


class FeedbackRequest(BaseModel):
    category: Literal["bug", "feature_request", "confusing_result", "general"]
    message: str = Field(min_length=3, max_length=5000)
    current_page: str | None = Field(default=None, max_length=255)
    dataset_id: str | None = None
    include_technical_context: bool = False
    request_id: str | None = Field(default=None, max_length=100)
    route: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=80)
    user_agent: str | None = Field(default=None, max_length=500)


class FeedbackAttachmentResponse(BaseModel):
    id: str; feedback_id: str; original_filename: str; content_type: str; size: int; created_at: datetime


class FeedbackResponse(BaseModel):
    id: str; category: str; message: str; current_page: str | None; dataset_id: str | None; status: str; created_at: datetime
    attachments: list[FeedbackAttachmentResponse] = Field(default_factory=list)


class AdminSummaryResponse(BaseModel):
    users: int; verified_users: int; workspaces: int; datasets: int; failed_jobs_24h: int; feedback: int; storage_bytes: int


class AdminDiagnosticsResponse(BaseModel):
    app_version: str; database: str; storage: str; queue: str; rate_limit_backend: str; storage_backend: str
    email_provider: str; email_configured: bool; last_email_status: str | None; last_email_operation: str | None


class SupportLookupResponse(BaseModel):
    results: list[dict[str, Any]]
