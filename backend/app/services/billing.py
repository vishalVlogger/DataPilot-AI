from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Subscription, Workspace
from app.services.commercial import plan_catalog


class BillingProvider(ABC):
    @abstractmethod
    def assign(self, session, workspace_id: str, plan_code: str, expires_at: datetime | None = None) -> Subscription: ...
    @abstractmethod
    def remove(self, session, workspace_id: str) -> Subscription | None: ...


class NoopBillingProvider(BillingProvider):
    def assign(self, session, workspace_id: str, plan_code: str, expires_at: datetime | None = None) -> Subscription:
        raise AppError("Manual subscription assignment is disabled.", "BILLING_PROVIDER_DISABLED", 409)
    def remove(self, session, workspace_id: str) -> Subscription | None:
        raise AppError("Manual subscription assignment is disabled.", "BILLING_PROVIDER_DISABLED", 409)


class ManualBillingProvider(BillingProvider):
    def assign(self, session, workspace_id: str, plan_code: str, expires_at: datetime | None = None) -> Subscription:
        if plan_code not in {"pro", "business"} or plan_code not in plan_catalog(): raise AppError("Manual plan must be Pro or Business.", "PLAN_INVALID", 422)
        if session.get(Workspace, workspace_id) is None: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        item = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id)); now = datetime.now(timezone.utc)
        if item is None:
            item = Subscription(workspace_id=workspace_id, plan_code=plan_code, status="active", billing_provider="manual", current_period_start=now, current_period_end=expires_at); session.add(item)
        else:
            item.plan_code = plan_code; item.status = "active"; item.billing_provider = "manual"; item.current_period_start = now; item.current_period_end = expires_at; item.cancel_at_period_end = False
        session.commit(); return item
    def remove(self, session, workspace_id: str) -> Subscription | None:
        item = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
        if item: item.status = "canceled"; item.cancel_at_period_end = False; session.commit()
        return item


def get_billing_provider(for_admin: bool = False) -> BillingProvider:
    configured = get_settings().billing_provider.casefold()
    if configured == "manual" or for_admin: return ManualBillingProvider()
    return NoopBillingProvider()
