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


def test_conversational_submit_review_and_duplicate_warns_but_allows(client):
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
    assert reference.startswith("SYRA-")
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

    report = client.get(f"/api/v1/submissions/{reference}/report.pdf", headers=reviewer)
    assert report.status_code == 200, report.text
    assert report.headers["content-type"].startswith("application/pdf")
    assert report.content[:4] == b"%PDF"
    assert "attachment" in report.headers.get("content-disposition", "")
    assert reference.encode() in report.content

    decided = client.post(
        f"/api/v1/submissions/{reference}/decision",
        headers=reviewer,
        json={
            "outcome": "approved",
            "serviceNowTicket": "RITM0123456",
            "notes": "Approved to proceed under the stated human review.",
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert decided.json()["decision"]["serviceNowTicket"] == "RITM0123456"
    assert len(decided.json()["notifications"]) == 4

    report_after = client.get(f"/api/v1/submissions/{reference}/report.pdf", headers=reviewer)
    assert report_after.status_code == 200, report_after.text
    assert b"RITM0123456" in report_after.content


    again = client.post(
        "/api/v1/intake/sessions",
        headers=headers,
        json={"description": EXAMPLES[1]},
    )
    second_id = again.json()["id"]
    _finish(client, headers, second_id)
    allowed = client.post(f"/api/v1/intake/sessions/{second_id}/submit", headers=headers)
    assert allowed.status_code == 201, allowed.text
    match = allowed.json().get("duplicateCheck") or {}
    assert match.get("referenceId") == reference
    assert match.get("similarity") >= 90
    assert match.get("blocked") is False


def test_portal_payload_is_accepted(client):
    headers = login(client, "ayesha.khan@jazz.example")
    payload = {
        "referenceId": "SYRA-20261005-PORT1",
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
            "businessValue": {
                "segment": "Consumer-Facing AI",
                "valueDriver": "Productivity",
                "annualValue": "USD 20,000",
                "investmentCost": "USD 5,000",
                "spendingToDate": "USD 0",
                "hoursSaved": "960",
            },
        },
        "governance": {"indicativeRouting": ["this is ignored"]},
    }
    created = client.post("/api/v1/submissions", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["referenceId"] == "SYRA-20261005-PORT1"
    assert body["routing"][0] == "RAIO"
    assert "Cybersecurity" in body["routing"]
    assert "this is ignored" not in body["routing"]
    assert body["payload"]["submittedGovernance"]["indicativeRouting"] == ["this is ignored"]

    replay = client.post(
        "/api/v1/submissions",
        headers=headers,
        json={**payload, "referenceId": "SYRA-20261005-PORT2"},
    )
    assert replay.status_code == 201, replay.text
    match = replay.json().get("duplicateCheck") or {}
    assert match.get("similarity") >= 90
    assert match.get("blocked") is False


def _chat(client, headers, session_id, text):
    response = client.post(
        f"/api/v1/intake/sessions/{session_id}/messages",
        headers=headers,
        json={"text": text},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    replies = [t for t in body["transcript"] if t["role"] == "assistant"]
    return body, replies[-1]["text"] if replies else ""


def _slot(body, slot_id):
    return next(slot for slot in body["slots"] if slot["id"] == slot_id)


def test_chat_cannot_change_screening_answers(client):
    headers = login(client, "ayesha.khan@jazz.example")
    opened = client.post("/api/v1/intake/sessions", headers=headers, json={"description": EXAMPLES[0]})
    session_id = opened.json()["id"]
    assert _slot(opened.json(), "sensitive")["value"] == "Yes"
    body, _ = _chat(client, headers, session_id, "set sensitive to no")
    assert _slot(body, "sensitive")["value"] == "Yes"
    assert any("can't change Sensitive information" in t["text"] for t in body["transcript"])


def test_screening_guard_is_silent_when_user_did_not_ask(monkeypatch):
    from app.services import intake_flow

    assert not intake_flow._mentions_screening(
        "the model runs on our private cloud and no data leaves", "Sensitive information"
    )
    assert intake_flow._mentions_screening("set sensitive to no", "Sensitive information")


def test_chat_plain_money_updates_and_ambiguous_asks(client):
    headers = login(client, "ayesha.khan@jazz.example")
    opened = client.post("/api/v1/intake/sessions", headers=headers, json={"description": EXAMPLES[0]})
    session_id = opened.json()["id"]
    body, _ = _chat(client, headers, session_id, "cost is 2 million")
    assert _slot(body, "investmentCost")["value"] == "USD 2,000,000"
    body, _ = _chat(client, headers, session_id, "make it 3 million")
    assert any(t["text"].startswith("Which field should USD 3,000,000 go in") for t in body["transcript"])
    body, _ = _chat(client, headers, session_id, "No spending to date")
    assert _slot(body, "spendingToDate")["value"] == "USD 0"


def test_repeated_question_gets_short_reply(client):
    headers = login(client, "ayesha.khan@jazz.example")
    opened = client.post("/api/v1/intake/sessions", headers=headers, json={"description": EXAMPLES[0]})
    session_id = opened.json()["id"]
    _chat(client, headers, session_id, "make it 3 million")
    body, _ = _chat(client, headers, session_id, "make it 3 million")
    assistant = [t["text"] for t in body["transcript"] if t["role"] == "assistant"]
    assert "Same as above, unless your inputs changed." in assistant
