
"""Integration tests for the AIMS semantic gatekeeper API."""

from app.api import gatekeeper_router as gatekeeper_api


DESCRIPTION = (
    "The AI reads customer complaints, "
    "identifies urgent issues and suggests solutions."
)


def login_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "ayesha.khan@jazz.example",
            "password": "JazzDemo-2026",
        },
    )

    assert response.status_code == 200, response.text

    return {
        "Authorization": (
            f"Bearer {response.json()['accessToken']}"
        )
    }


def successful_result():
    return {
        "status": "complete",
        "validated": True,
        "retryable": False,
        "complete": True,
        "fields": {
            "data": {
                "status": "complete",
                "value": "Customer complaints",
                "evidence": "customer complaints",
                "question": "",
            },
            "decisions": {
                "status": "complete",
                "value": "Identify urgent issues",
                "evidence": "identifies urgent issues",
                "question": "",
            },
            "actions": {
                "status": "complete",
                "value": "Suggest solutions",
                "evidence": "suggests solutions",
                "question": "",
            },
        },
        "missing": [],
        "nextQuestion": "",
        "message": (
            "Your description has the details needed to continue."
        ),
        "errorCode": None,
    }


def unavailable_result():
    return {
        "status": "unavailable",
        "validated": False,
        "retryable": True,
        "complete": False,
        "fields": {
            name: {
                "status": "needs_clarification",
                "value": "",
                "evidence": "",
                "question": "",
            }
            for name in ("data", "decisions", "actions")
        },
        "missing": [],
        "nextQuestion": "",
        "message": (
            "I'm having trouble checking your description right now. "
            "Everything you've entered is still here. Please try again."
        ),
        "errorCode": "validation_failed",
    }


def test_gatekeeper_requires_login(client):
    response = client.post(
        "/api/v1/gatekeeper/validate",
        json={
            "description": DESCRIPTION,
            "answers": [],
        },
    )

    assert response.status_code == 401


def test_gatekeeper_endpoint_returns_validation(
    client,
    monkeypatch,
):
    captured = {}

    def fake_validate(description, answers, settings):
        captured["description"] = description
        captured["answers"] = answers
        return successful_result()

    monkeypatch.setattr(
        gatekeeper_api,
        "validate_definition",
        fake_validate,
    )

    headers = login_headers(client)

    response = client.post(
        "/api/v1/gatekeeper/validate",
        headers=headers,
        json={
            "description": DESCRIPTION,
            "answers": [],
        },
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["status"] == "complete"
    assert result["validated"] is True
    assert result["complete"] is True
    assert result["retryable"] is False

    assert result["fields"]["data"]["value"] == (
        "Customer complaints"
    )

    assert captured["description"] == DESCRIPTION
    assert captured["answers"] == []


def test_gatekeeper_preserves_clarification_history(
    client,
    monkeypatch,
):
    captured = {}

    def fake_validate(description, answers, settings):
        captured["description"] = description
        captured["answers"] = answers
        return successful_result()

    monkeypatch.setattr(
        gatekeeper_api,
        "validate_definition",
        fake_validate,
    )

    answers = [
        {
            "question": "What information does it process?",
            "answer": "Customer complaints",
        },
        {
            "question": "What does it do?",
            "answer": "Suggests possible solutions",
        },
    ]

    original_answers = [
        dict(item)
        for item in answers
    ]

    headers = login_headers(client)

    response = client.post(
        "/api/v1/gatekeeper/validate",
        headers=headers,
        json={
            "description": DESCRIPTION,
            "answers": answers,
        },
    )

    assert response.status_code == 200, response.text

    assert captured["description"] == DESCRIPTION
    assert captured["answers"] == original_answers
    assert answers == original_answers


def test_gatekeeper_model_failure_is_retryable(
    client,
    monkeypatch,
):
    def fake_validate(description, answers, settings):
        return unavailable_result()

    monkeypatch.setattr(
        gatekeeper_api,
        "validate_definition",
        fake_validate,
    )

    headers = login_headers(client)

    response = client.post(
        "/api/v1/gatekeeper/validate",
        headers=headers,
        json={
            "description": DESCRIPTION,
            "answers": [
                {
                    "question": "What data?",
                    "answer": "Customer records",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["status"] == "unavailable"
    assert result["validated"] is False
    assert result["complete"] is False
    assert result["retryable"] is True

    assert result["errorCode"] == "validation_failed"
    assert result["nextQuestion"] == ""

    assert "Everything you've entered" in result["message"]


def test_gatekeeper_rejects_invalid_input(client):
    headers = login_headers(client)

    response = client.post(
        "/api/v1/gatekeeper/validate",
        headers=headers,
        json={
            "description": "",
            "answers": [],
        },
    )

    assert response.status_code == 422


def test_existing_intake_endpoint_still_available(client):
    headers = login_headers(client)

    response = client.get(
        "/api/v1/intake/examples",
        headers=headers,
    )

    assert response.status_code == 200
    assert "examples" in response.json()
