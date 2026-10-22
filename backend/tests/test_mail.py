from app.config import Settings
from app.mail.providers.log import LogMailProvider
from app.mail.service import get_mail_provider, send_mail
from app.services.emailer import submission_notice


def test_auto_provider_falls_back_to_log_without_credentials():
    settings = Settings(
        mail_provider="auto",
        smtp_host="",
        graph_tenant_id="",
        graph_client_id="",
        graph_client_secret="",
        graph_sender="",
    )
    provider = get_mail_provider(settings)
    assert provider.name == "log"
    assert isinstance(provider, LogMailProvider)


def test_smtp_provider_selected_when_host_set():
    settings = Settings(
        mail_provider="smtp",
        smtp_host="smtp.office365.com",
        smtp_from="raio@jazz.example",
    )
    assert get_mail_provider(settings).name == "smtp"


def test_graph_provider_selected_when_credentials_set():
    settings = Settings(
        mail_provider="graph",
        graph_tenant_id="tenant",
        graph_client_id="client",
        graph_client_secret="secret",
        graph_sender="raio@jazz.example",
    )
    assert get_mail_provider(settings).name == "graph"


def test_send_mail_logs_when_unconfigured():
    settings = Settings(mail_provider="log")
    result = send_mail(
        "ayesha.khan@jazz.example",
        "Test",
        "Body",
        settings=settings,
    )
    assert result.status == "logged"
    assert result.provider == "log"


def test_submission_notice_includes_reference():
    payload = {
        "referenceId": "AIRA-20261008-TEST1",
        "submittedAt": "2026-10-08T00:00:00Z",
        "category": "AI For Us",
        "screening": {"data": "Yes", "decision": "No", "action": "No"},
        "screeningEffective": {"data": "Yes", "decision": "No", "action": "No"},
        "aiSystem": {
            "name": "Copilot rollout",
            "businessOwner": "Ayesha Khan",
            "businessUnit": "Technology",
            "summary": "Roll out Copilot",
            "description": "Enterprise Copilot for contracts",
        },
        "governance": {
            "earlyFlags": [{"level": "attention", "title": "External provider"}],
            "indicativeRouting": ["RAIO", "Privacy / Data Protection"],
        },
    }
    subject, body = submission_notice(payload, "Ayesha Khan", "ayesha.khan@jazz.example")
    assert "AIRA-20261008-TEST1" in subject
    assert "Copilot rollout" in body
    assert "RAIO" in body
