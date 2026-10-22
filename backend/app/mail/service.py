from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.mail.base import MailMessage, MailProvider, MailResult
from app.mail.providers.graph import GraphMailProvider
from app.mail.providers.log import LogMailProvider
from app.mail.providers.smtp_outlook import OutlookSmtpProvider

logger = logging.getLogger(__name__)


def get_mail_provider(settings: Settings | None = None) -> MailProvider:
    settings = settings or get_settings()
    choice = (settings.mail_provider or "auto").strip().lower()

    smtp = OutlookSmtpProvider(settings)
    graph = GraphMailProvider(settings)
    log = LogMailProvider()

    if choice == "log":
        return log
    if choice == "smtp":
        return smtp if smtp.configured() else log
    if choice == "graph":
        return graph if graph.configured() else log
    if choice == "auto":
        if graph.configured():
            return graph
        if smtp.configured():
            return smtp
        return log
    logger.warning("Unknown MAIL_PROVIDER=%s; using log", choice)
    return log


def send_mail(
    to: str | list[str],
    subject: str,
    body_text: str,
    *,
    body_html: str | None = None,
    cc: list[str] | None = None,
    reply_to: str | None = None,
    settings: Settings | None = None,
) -> MailResult:
    settings = settings or get_settings()
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [addr.strip() for addr in recipients if addr and addr.strip()]
    if not recipients:
        return MailResult(status="skipped", provider="none", detail="No recipients")

    message = MailMessage(
        to=recipients,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        cc=[addr.strip() for addr in (cc or []) if addr and addr.strip()],
        reply_to=reply_to or settings.mail_reply_to or None,
    )
    provider = get_mail_provider(settings)
    if settings.mail_enabled is False:
        logger.info("Mail disabled (MAIL_ENABLED=false); logging only.")
        return LogMailProvider().send(message)
    return provider.send(message)


def mail_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    provider = get_mail_provider(settings)
    return {
        "enabled": settings.mail_enabled,
        "provider": provider.name,
        "configured": provider.configured(),
        "fromAddress": settings.smtp_from or settings.graph_sender or "",
        "governanceEmail": settings.governance_email,
    }
