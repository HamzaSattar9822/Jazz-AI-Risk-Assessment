from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class MailMessage:
    to: list[str]
    subject: str
    body_text: str
    body_html: str | None = None
    cc: list[str] = field(default_factory=list)
    reply_to: str | None = None


@dataclass
class MailResult:
    status: str  # sent | logged | failed | skipped
    provider: str
    detail: str = ""
    message_id: str | None = None


class MailProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def send(self, message: MailMessage) -> MailResult: ...
