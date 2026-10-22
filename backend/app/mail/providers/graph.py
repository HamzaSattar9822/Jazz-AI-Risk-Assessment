"""Microsoft Graph mail provider (Outlook in Microsoft 365).

App registration (Entra ID / Azure AD):
  1. Register an application
  2. Add application permission: Mail.Send
  3. Grant admin consent
  4. Create a client secret
  5. Set GRAPH_* values in .env and MAIL_PROVIDER=graph

Sends as GRAPH_SENDER (user principal name or mailbox), not as the app itself.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.mail.base import MailMessage, MailResult

logger = logging.getLogger(__name__)

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


class GraphMailProvider:
    name = "graph"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None

    def configured(self) -> bool:
        s = self.settings
        return bool(
            s.graph_tenant_id
            and s.graph_client_id
            and s.graph_client_secret
            and s.graph_sender
        )

    def send(self, message: MailMessage) -> MailResult:
        if not self.configured():
            return MailResult(
                status="skipped",
                provider=self.name,
                detail="GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, and GRAPH_SENDER are required.",
            )
        try:
            token = self._access_token()
            payload = self._payload(message)
            response = httpx.post(
                SEND_URL.format(sender=self.settings.graph_sender),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.mail_timeout_seconds,
            )
            if response.status_code not in {202, 200}:
                detail = response.text[:500]
                logger.warning("Graph sendMail failed (%s): %s", response.status_code, detail)
                return MailResult(
                    status="failed",
                    provider=self.name,
                    detail=f"HTTP {response.status_code}: {detail}",
                )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Graph mail failed: %s", exc)
            return MailResult(status="failed", provider=self.name, detail=str(exc))

        return MailResult(status="sent", provider=self.name, detail="Accepted by Microsoft Graph")

    def _access_token(self) -> str:
        if self._token:
            return self._token
        data = {
            "client_id": self.settings.graph_client_id,
            "client_secret": self.settings.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        response = httpx.post(
            TOKEN_URL.format(tenant=self.settings.graph_tenant_id),
            data=data,
            timeout=self.settings.mail_timeout_seconds,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Graph token response had no access_token")
        self._token = token
        return token

    def _payload(self, message: MailMessage) -> dict[str, Any]:
        content_type = "HTML" if message.body_html else "Text"
        content = message.body_html or message.body_text
        to_recipients = [{"emailAddress": {"address": addr}} for addr in message.to]
        cc_recipients = [{"emailAddress": {"address": addr}} for addr in message.cc]
        msg: dict[str, Any] = {
            "message": {
                "subject": message.subject,
                "body": {"contentType": content_type, "content": content},
                "toRecipients": to_recipients,
            },
            "saveToSentItems": True,
        }
        if cc_recipients:
            msg["message"]["ccRecipients"] = cc_recipients
        if message.reply_to:
            msg["message"]["replyTo"] = [{"emailAddress": {"address": message.reply_to}}]
        return msg
