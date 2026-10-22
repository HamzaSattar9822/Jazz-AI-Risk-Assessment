"""Outlook / Microsoft 365 SMTP provider.

Typical Jazz / M365 values:
  MAIL_PROVIDER=smtp
  SMTP_HOST=smtp.office365.com
  SMTP_PORT=587
  SMTP_TLS=true
  SMTP_USER=raio@yourdomain.com
  SMTP_PASSWORD=<app password or mailbox password>
  SMTP_FROM=raio@yourdomain.com

IT may require SMTP AUTH enabled for the mailbox, or prefer Graph instead.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings
from app.mail.base import MailMessage, MailResult

logger = logging.getLogger(__name__)


class OutlookSmtpProvider:
    name = "smtp"

    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_from)

    def send(self, message: MailMessage) -> MailResult:
        if not self.configured():
            return MailResult(
                status="skipped",
                provider=self.name,
                detail="SMTP_HOST and SMTP_FROM are required for Outlook SMTP.",
            )

        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self.settings.smtp_from
        email["To"] = ", ".join(message.to)
        if message.cc:
            email["Cc"] = ", ".join(message.cc)
        if message.reply_to:
            email["Reply-To"] = message.reply_to
        email.set_content(message.body_text)
        if message.body_html:
            email.add_alternative(message.body_html, subtype="html")

        recipients = list(message.to) + list(message.cc)
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.mail_timeout_seconds,
            ) as smtp:
                if self.settings.smtp_tls:
                    smtp.starttls(context=context)
                if self.settings.smtp_user:
                    smtp.login(self.settings.smtp_user, self.settings.smtp_password)
                smtp.send_message(email, to_addrs=recipients)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("Outlook SMTP send failed: %s", exc)
            return MailResult(status="failed", provider=self.name, detail=str(exc))

        return MailResult(status="sent", provider=self.name, detail="Delivered via SMTP")
