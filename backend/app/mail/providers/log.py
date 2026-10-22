from __future__ import annotations

import logging

from app.mail.base import MailMessage, MailResult

logger = logging.getLogger(__name__)


class LogMailProvider:
    """Dev / default provider: does not leave the host."""

    name = "log"

    def configured(self) -> bool:
        return True

    def send(self, message: MailMessage) -> MailResult:
        recipients = ", ".join(message.to)
        logger.info("Mail logged (not sent) to %s | %s", recipients, message.subject)
        return MailResult(
            status="logged",
            provider=self.name,
            detail="MAIL_PROVIDER=log or no Outlook credentials configured.",
        )
