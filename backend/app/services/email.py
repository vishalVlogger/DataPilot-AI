import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger("datapilot.email")
console_outbox: list[dict[str, str]] = []


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(self, recipient: str, subject: str, text: str) -> None: ...


class ConsoleEmailProvider(EmailProvider):
    async def send_email(self, recipient: str, subject: str, text: str) -> None:
        console_outbox.append({"recipient": recipient, "subject": subject, "text": text})
        logger.info("Console email to %s — %s\n%s", recipient, subject, text)


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
        except Exception as exc: raise AppError("Email delivery failed.", "EMAIL_DELIVERY_FAILED", 503) from exc


def get_email_provider() -> EmailProvider:
    provider = get_settings().email_provider.casefold()
    if provider == "console": return ConsoleEmailProvider()
    if provider == "smtp": return SMTPEmailProvider()
    raise AppError("Unknown email provider.", "EMAIL_PROVIDER_INVALID", 500)
