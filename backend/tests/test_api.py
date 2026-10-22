import json
from pathlib import Path

from app.intake.catalog import EXAMPLES
from app.methodology.engine import CONTROL_FACTORS, IMPACT_FACTORS, LIKELIHOOD_FACTORS

GOLDENS = json.loads(Path(__file__).parent.joinpath("fixtures/aira_goldens.json").read_text())


def login(client, email):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "JazzDemo-2026"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def _uniform(score):
    return {
        "impact": {
            group: {name: score for name in names} for group, names in IMPACT_FACTORS.items()
        },
        "likelihood": {
            group: {name: score for name in names} for group, names in LIKELIHOOD_FACTORS.items()
        },
        "controls": {name: score for name in CONTROL_FACTORS},
    }


def _finish(client, headers, session_id):
    for _ in range(30):
        view = client.get(f"/api/v1/intake/sessions/{session_id}", headers=headers)
        assert view.status_code == 200, view.text
        body = view.json()
        if body["readyToSubmit"]:
            return body
        if body["pendingConfirmation"]:
            confirmed = client.post(
                f"/api/v1/intake/sessions/{session_id}/confirm",
                headers=headers,
                json={"slotIds": [slot["id"] for slot in body["pendingConfirmation"]]},
            )
            assert confirmed.status_code == 200, confirmed.text
            continue
        question = body["nextQuestion"]
        assert question, body
        if question["kind"] == "text":
            value = "Pilot request"
        elif question["kind"] == "multi":
            value = [question["options"][0]["value"]]
        else:
            value = question["options"][0]["value"]
        answered = client.post(
            f"/api/v1/intake/sessions/{session_id}/answers",
            headers=headers,
            json={"slotId": question["id"], "value": value},
        )
        assert answered.status_code == 200, answered.text
    raise AssertionError("intake did not finish")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["methodology"] == "AIRA-DDA-1.0"
    assert response.json()["llmConfigured"] is False


def test_conversational_submit_review_and_duplicate_block(client):
    headers = login(client, "ayesha.khan@jazz.example")
    opened = client.post(
        "/api/v1/intake/sessions",
        headers=headers,
        json={"description": EXAMPLES[1]},
    )
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["id"]
    assert opened.json()["extractor"] == "keyword"
    assert any(
        slot["id"] == "name" and slot["value"] == "Credit Line Recommender"
        for slot in opened.json()["slots"]
    )

    _finish(client, headers, session_id)
    submitted = client.post(f"/api/v1/intake/sessions/{session_id}/submit", headers=headers)
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    reference = body["referenceId"]
    assert reference.startswith("AIRA-")
    assert body["status"] == "submitted"
    assert body["payload"]["category"] == "AI By Us"
    assert body["payload"]["aiSystem"]["businessOwner"] == "Ayesha Khan"
    assert "Technology / Architecture" in body["routing"]
    assert "Legal / Compliance" in body["routing"]
    assert any(
        flag["title"] == "Sensitive information goes to an outside provider"
        for flag in body["earlyFlags"]
    )
    recipients = {note["recipient"] for note in body["notifications"]}
    assert recipients == {"ayesha.khan@jazz.example", "sana.malik@jazz.example"}
    assert {note["status"] for note in body["notifications"]} == {"logged"}
    assert reference in body["notifications"][0]["subject"]

    denied = client.post(
        f"/api/v1/submissions/{reference}/assessment",
        headers=headers,
        json={"scores": _uniform(3)},
    )
    assert denied.status_code == 403

    reviewer = login(client, "rahim.qureshi@jazz.example")
    assessed = client.post(
        f"/api/v1/submissions/{reference}/assessment",
        headers=reviewer,
        json={
            "scores": _uniform(3),
            "notes": "Initial RAIO score.",
            "humanReview": {"status": "APPROVED", "reviewedBy": "rahim.qureshi@jazz.example"},
        },
    )
    assert assessed.status_code == 200, assessed.text
    expected = next(case["result"] for case in GOLDENS["cases"] if case["name"] == "uniform-3-all")
    result = assessed.json()["assessment"]["result"]
    assert result["residualRiskScore"] == expected["residualRiskScore"]
    assert result["inherentRiskScore"] == expected["inherentRiskScore"]
    assert result["residualRiskGovernance"] == expected["residualRiskGovernance"]
    assert assessed.json()["status"] == "in_review"

    decided = client.post(
        f"/api/v1/submissions/{reference}/decision",
        headers=reviewer,
        json={"outcome": "approved", "notes": "Approved to proceed under the stated human review."},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert len(decided.json()["notifications"]) == 4

    again = client.post(
        "/api/v1/intake/sessions",
        headers=headers,
        json={"description": EXAMPLES[1]},
    )
    second_id = again.json()["id"]
    _finish(client, headers, second_id)
    blocked = client.post(f"/api/v1/intake/sessions/{second_id}/submit", headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "duplicate"
    assert blocked.json()["detail"]["match"]["referenceId"] == reference
    assert blocked.json()["detail"]["match"]["similarity"] >= 90


def test_portal_payload_is_accepted(client):
    headers = login(client, "ayesha.khan@jazz.example")
    payload = {
        "referenceId": "AIRA-20261005-PORT1",
        "category": "AI Against Us",
        "screening": {"data": "Yes", "decision": "No", "action": "No"},
        "aiSystem": {
            "name": "Executive voice clone",
            "businessOwner": "Ayesha Khan",
            "businessUnit": "Technology",
            "summary": "Assess deepfake payment fraud against finance staff.",
            "description": "Voice-cloned calls are impersonating executives and asking finance to approve urgent payments.",
        },
        "conditionalInformation": {
            "aiAgainstUs": {"threatTypes": ["Deepfake / impersonation", "Fraud / scam"]},
            "data": {"externalProcessing": "No"},
        },
        "governance": {"indicativeRouting": ["this is ignored"]},
    }
    created = client.post("/api/v1/submissions", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["referenceId"] == "AIRA-20261005-PORT1"
    assert body["routing"][0] == "RAIO"
    assert "Cybersecurity" in body["routing"]
    assert "this is ignored" not in body["routing"]
    assert body["payload"]["submittedGovernance"]["indicativeRouting"] == ["this is ignored"]

    replay = client.post(
        "/api/v1/submissions",
        headers=headers,
        json={**payload, "referenceId": "AIRA-20261005-PORT2"},
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "duplicate"
