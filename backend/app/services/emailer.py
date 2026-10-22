"""Submission and decision notices via the Outlook / Graph mail framework."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.mail import MailMessage, send_mail
from app.mail.service import get_mail_provider
from app.models import Notification, Submission

logger = logging.getLogger(__name__)


def submission_notice(payload: dict, requester_name: str, requester_email: str) -> tuple[str, str]:
    system = payload["aiSystem"]
    flags = payload["governance"]["earlyFlags"]
    flag_lines = "\n".join(f"- {item['level']}: {item['title']}" for item in flags) or "- None"
    routing = ", ".join(payload["governance"]["indicativeRouting"])
    subject = f"JazzWorld AI approval request {payload['referenceId']}"
    body = "\n".join(
        [
            f"Reference: {payload['referenceId']}",
            f"Submitted: {payload['submittedAt']}",
            f"Requester: {requester_name} <{requester_email}>",
            f"Category: {payload['category']}",
            f"Name: {system['name']}",
            f"Business owner: {system['businessOwner']}",
            f"Business unit: {system['businessUnit']}",
            "",
            "Summary:",
            system.get("summary") or "",
            "",
            "Description:",
            system.get("description") or "",
            "",
            "Screening (as answered):",
            f"- Sensitive information: {payload['screening']['data']}",
            f"- Affects decisions: {payload['screening']['decision']}",
            f"- Interacts or acts: {payload['screening']['action']}",
            "",
            "Screening (effective):",
            f"- Sensitive information: {payload['screeningEffective']['data']}",
            f"- Affects decisions: {payload['screeningEffective']['decision']}",
            f"- Interacts or acts: {payload['screeningEffective']['action']}",
            "",
            "Early flags:",
            flag_lines,
            "",
            f"Indicative routing: {routing}",
            "",
            "Risk scoring and the decision are made by the Responsible AI Office.",
            "You will receive the outcome and any conditions before use begins.",
        ]
    )
    return subject, body


def decision_notice(submission: Submission) -> tuple[str, str]:
    decision = submission.decision or {}
    outcome = decision.get("outcome", "")
    label = outcome.replace("_", " ")
    subject = f"JazzWorld AI approval decision {submission.reference_id}"
    lines = [
        f"Reference: {submission.reference_id}",
        f"Decision: {label}",
        f"Decided by: {decision.get('decidedBy', '')}",
    ]
    if decision.get("conditions"):
        lines.extend(["", "Conditions:", decision["conditions"]])
    if decision.get("notes"):
        lines.extend(["", "Notes:", decision["notes"]])
    assessment = submission.assessment or {}
    result = assessment.get("result") or {}
    if result.get("complete"):
        governance = result.get("residualRiskGovernance") or result
        severity = governance.get("severity") or result.get("severity") or ""
        approval = governance.get("approval") or result.get("approvalLevel") or ""
        lines.extend(
            [
                "",
                f"Residual risk score: {result.get('residualRiskScore')}",
                f"Severity: {severity}",
                f"Suggested approval level: {approval}",
            ]
        )
    return subject, "\n".join(lines)


def _html_from_text(subject: str, body: str) -> str:
    escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return (
        "<html><body style=\"font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#222\">"
        f"<h2 style=\"color:#880939\">{subject}</h2>"
        f"<p>{escaped}</p>"
        "<p style=\"color:#666;font-size:12px\">JazzWorld Responsible AI Office (RAIO)</p>"
        "</body></html>"
    )


def notify(
    db: Session,
    settings: Settings,
    submission: Submission,
    recipient: str,
    role: str,
    subject: str,
    body: str,
) -> Notification:
    result = send_mail(
        recipient,
        subject,
        body,
        body_html=_html_from_text(subject, body),
        settings=settings,
    )
    if result.status == "failed":
        logger.warning(
            "Notice to %s via %s failed: %s",
            recipient,
            result.provider,
            result.detail,
        )
    row = Notification(
        submission_id=submission.id,
        recipient=recipient,
        role=role,
        subject=subject,
        body=body,
        status=result.status,
    )
    db.add(row)
    return row


def probe_mail(settings: Settings, to: str) -> dict:
    """Send a short connectivity check (used by the mail test endpoint)."""
    provider = get_mail_provider(settings)
    subject = "JazzWorld AIRA mail connectivity check"
    body = (
        f"This is a test message from the AIRA mail framework.\n"
        f"Provider: {provider.name}\n"
        f"If you received this, Outlook / Graph delivery is working."
    )
    result = send_mail(to, subject, body, body_html=_html_from_text(subject, body), settings=settings)
    return {
        "to": to,
        "provider": result.provider,
        "status": result.status,
        "detail": result.detail,
    }
