"""SMTP notifications (M5). Unconfigured SMTP means notifications are
skipped, never crashed on — the run pipeline must not depend on a mail
server being up."""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import structlog

from api.config import get_settings

log = structlog.get_logger()


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str  # e.g. "application/pdf", "text/csv"


def smtp_configured() -> bool:
    return bool(get_settings().smtp_host)


def send_email(
    to: list[str], subject: str, body: str, attachments: list[Attachment] | None = None
) -> bool:
    settings = get_settings()
    if not settings.smtp_host or not to:
        reason = "smtp not configured" if not settings.smtp_host else "no recipients"
        log.info("email.skipped", reason=reason)
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    for attachment in attachments or []:
        maintype, _, subtype = attachment.mime_type.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
    log.info("email.sent", to=to, subject=subject)
    return True
