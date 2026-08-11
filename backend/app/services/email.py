import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.observability import current_request_id

logger = logging.getLogger("datapilot.email")
console_outbox: list[dict[str, str]] = []
_last_delivery: dict[str, Any] = {"status": None, "operation": None, "provider": None, "attempted_at": None, "classification": None}


@dataclass(frozen=True)
class EmailDeliveryResult:
    provider: str
    status: str


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(self, recipient: str, subject: str, text: str) -> None: ...


class ConsoleEmailProvider(EmailProvider):
    async def send_email(self, recipient: str, subject: str, text: str) -> None:
        console_outbox.append({"recipient": recipient, "subject": subject, "text": text})
        logger.info("console_email_captured", extra={"email_provider": "console"})


class SMTPEmailProvider(EmailProvider):
    async def send_email(self, recipient: str, subject: str, text: str) -> None:
        settings = get_settings()
        if not settings.smtp_host: raise AppError("SMTP is not configured.", "EMAIL_PROVIDER_INVALID", 503)
        message = EmailMessage(); message["From"] = settings.email_from; message["To"] = recipient; message["Subject"] = subject; message.set_content(text)
        def deliver() -> None:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                if settings.smtp_use_tls: client.starttls()
                if settings.smtp_username: client.login(settings.smtp_username, settings.smtp_password or "")
                client.send_message(message)
        try: await asyncio.to_thread(deliver)
        except Exception as exc: raise AppError("The email provider could not accept this message. Please try again.", "EMAIL_DELIVERY_FAILED", 503) from exc


def get_email_provider() -> EmailProvider:
    provider = get_settings().email_provider.casefold()
    if provider == "console": return ConsoleEmailProvider()
    if provider == "smtp": return SMTPEmailProvider()
    raise AppError("Unknown email provider.", "EMAIL_PROVIDER_INVALID", 500)


async def send_transactional_email(recipient: str, subject: str, text: str, operation: str) -> EmailDeliveryResult:
    settings = get_settings(); provider_name = settings.email_provider.casefold(); attempted_at = datetime.now(timezone.utc).isoformat()
    try:
        await get_email_provider().send_email(recipient, subject, text)
    except Exception as exc:
        classification = "configuration" if isinstance(exc, AppError) and exc.error_code == "EMAIL_PROVIDER_INVALID" else "authentication" if isinstance(exc.__cause__, smtplib.SMTPAuthenticationError) else "timeout" if isinstance(exc.__cause__, TimeoutError) else "connection"
        _last_delivery.update({"status": "failed", "operation": operation, "provider": provider_name, "attempted_at": attempted_at, "classification": classification})
        logger.error("email_delivery_failed", extra={"request_id": current_request_id(), "email_provider": provider_name, "email_operation": operation, "error_classification": classification})
        raise
    _last_delivery.update({"status": "success", "operation": operation, "provider": provider_name, "attempted_at": attempted_at, "classification": None})
    logger.info("email_delivery_succeeded", extra={"request_id": current_request_id(), "email_provider": provider_name, "email_operation": operation})
    return EmailDeliveryResult(provider=provider_name, status="success")


def email_delivery_diagnostics() -> dict[str, Any]:
    return dict(_last_delivery)
