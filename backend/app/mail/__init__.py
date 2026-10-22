"""Outbound mail framework for JazzWorld AIRA.

Providers:
- log: store only (default when nothing is configured)
- smtp: Outlook / Microsoft 365 SMTP (smtp.office365.com)
- graph: Microsoft Graph sendMail (app registration + client credentials)

Submission and decision notices call send_mail(); they do not talk to Outlook
directly. Swap providers with MAIL_PROVIDER in .env.
"""

from app.mail.service import MailMessage, MailResult, get_mail_provider, send_mail

__all__ = ["MailMessage", "MailResult", "get_mail_provider", "send_mail"]
