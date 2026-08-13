from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    invitation_token: str | None = Field(default=None, min_length=20, max_length=500)
    beta_acknowledged: bool = False
    acquisition_source: Literal["open_registration", "workspace_invitation", "beta_invite", "partner", "referral", "other"] = "open_registration"

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must contain letters and numbers")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str; email: EmailStr; display_name: str; is_active: bool; is_system_admin: bool = False; email_verified_at: datetime | None = None; beta_acknowledged_at: datetime | None = None; created_at: datetime; last_login_at: datetime | None
    acquisition_source: str = "open_registration"; beta_status: str = "onboarding"


class WorkspaceResponse(BaseModel):
    id: str; name: str; slug: str; owner_user_id: str; role: Literal["owner", "admin", "member"]; plan_code: str; external_ai_enabled: bool = True; created_at: datetime; updated_at: datetime; deletion_requested_at: datetime | None = None; deletion_scheduled_for: datetime | None = None


class AuthResponse(BaseModel):
    access_token: str; token_type: str = "bearer"; expires_in: int; user: UserResponse; workspaces: list[WorkspaceResponse]
    email_delivery_status: str | None = None
    development_verification_url: str | None = None


class CurrentUserResponse(BaseModel):
    user: UserResponse; workspaces: list[WorkspaceResponse]


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    external_ai_enabled: bool | None = None


class UsageSummaryResponse(BaseModel):
    plan_code: str; datasets: int; storage_bytes: int; analyses_this_month: int; ai_requests_this_month: int; reports_this_month: int; rows_this_month: int; limits: dict[str, int]; percentages: dict[str, float]


class ActivityResponse(BaseModel):
    id: str; activity_type: str; user_id: str | None; resource_id: str | None; details: dict[str, Any] | None; created_at: datetime


class DashboardResponse(BaseModel):
    usage: UsageSummaryResponse; recent_datasets: list[dict[str, Any]]; recent_activity: list[ActivityResponse]


class UserUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)


class ResetPasswordRequest(TokenRequest):
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def reset_password_strength(cls, value: str) -> str:
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value): raise ValueError("Password must contain letters and numbers")
        return value


class BetaAcknowledgementRequest(BaseModel):
    acknowledged: bool
