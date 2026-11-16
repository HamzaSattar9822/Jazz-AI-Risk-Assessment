
"""Tests for AIMS semantic gatekeeper."""

import json

import httpx

from app.config import Settings
from app.services import gatekeeper


def settings():
    return Settings(
        llm_base_url="https://example.invalid/v1",
        llm_model="test-model",
        llm_require_api_key=False,
    )


def mock_response(monkeypatch, result):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(result)
                        }
                    }
                ]
            }

    def fake_post(*args, **kwargs):
        return Response()

    monkeypatch.setattr(
        gatekeeper.httpx,
        "post",
        fake_post,
    )


def complete_result():
    return {
        "data": {
            "status": "complete",
            "value": "Customer complaints",
            "evidence": "customer complaints",
            "question": "",
        },
        "decisions": {
            "status": "complete",
            "value": "Find urgent issues",
            "evidence": "identifies urgent issues",
            "question": "",
        },
        "actions": {
            "status": "complete",
            "value": "Suggest solutions",
            "evidence": "suggests solutions",
            "question": "",
        },
    }


DESCRIPTION = (
    "The AI reads customer complaints, "
    "identifies urgent issues and suggests solutions."
)


def test_complete_description(monkeypatch):
    mock_response(monkeypatch, complete_result())

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        [],
        settings(),
    )

    assert result["validated"] is True
    assert result["complete"] is True
    assert result["status"] == "complete"
    assert result["missing"] == []
    assert result["nextQuestion"] == ""


def test_missing_action_requires_one_question(monkeypatch):
    result_data = complete_result()

    result_data["actions"] = {
        "status": "needs_clarification",
        "value": "Handles refunds",
        "evidence": "handles refunds",
        "question": (
            "Can the AI issue refunds itself, "
            "or only recommend them?"
        ),
    }

    mock_response(monkeypatch, result_data)

    result = gatekeeper.validate_definition(
        (
            "The AI reads customer complaints, "
            "identifies urgent issues and handles refunds."
        ),
        [],
        settings(),
    )

    assert result["validated"] is True
    assert result["complete"] is False
    assert result["missing"] == ["actions"]
    assert "refunds" in result["nextQuestion"]


def test_answers_are_preserved_and_sent_again(monkeypatch):
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs["json"])

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    complete_result()
                                )
                            }
                        }
                    ]
                }

        return Response()

    monkeypatch.setattr(
        gatekeeper.httpx,
        "post",
        fake_post,
    )

    answers = [
        {
            "question": "Who can send responses?",
            "answer": "Only a human agent.",
        }
    ]

    original_answers = [
        dict(answer)
        for answer in answers
    ]

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        answers,
        settings(),
    )

    sent = captured["messages"][1]["content"]

    assert DESCRIPTION in sent
    assert "Only a human agent." in sent
    assert answers == original_answers
    assert result["complete"] is True
    assert captured["max_tokens"] == 1500


def test_network_failure_never_completes(monkeypatch):
    def failing_post(*args, **kwargs):
        raise httpx.ConnectError(
            "Simulated model connection failure"
        )

    monkeypatch.setattr(
        gatekeeper.httpx,
        "post",
        failing_post,
    )

    answers = [
        {
            "question": "What data?",
            "answer": "Customer records",
        }
    ]

    original = [dict(item) for item in answers]

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        answers,
        settings(),
    )

    assert result["status"] == "unavailable"
    assert result["validated"] is False
    assert result["complete"] is False
    assert result["retryable"] is True
    assert answers == original


def test_unsupported_evidence_is_rejected(monkeypatch):
    data = complete_result()

    data["actions"]["evidence"] = (
        "The AI automatically transfers money"
    )

    mock_response(monkeypatch, data)

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        [],
        settings(),
    )

    assert result["status"] == "unavailable"
    assert result["validated"] is False
    assert result["complete"] is False


def test_invalid_model_json_fails_safely(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "This is not valid JSON"
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        gatekeeper.httpx,
        "post",
        lambda *args, **kwargs: Response(),
    )

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        [],
        settings(),
    )

    assert result["status"] == "unavailable"
    assert result["retryable"] is True
    assert result["validated"] is False


def test_unconfigured_model_fails_safely():
    unconfigured = Settings(
        llm_base_url="",
        llm_require_api_key=False,
    )

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        [],
        unconfigured,
    )

    assert result["status"] == "unavailable"
    assert result["complete"] is False
    assert result["retryable"] is True


# ---------------------------------------------------------------
# Additional reasoning-model response tests
# ---------------------------------------------------------------

def test_complete_reasoning_block_is_removed():
    content = (
        "<think>Internal model reasoning.</think>\n"
        + json.dumps(complete_result())
    )

    parsed = gatekeeper._parse_json(content)

    assert parsed == complete_result()


def test_missing_opening_think_tag_is_handled():
    content = (
        "Internal reasoning without an opening tag."
        "</think>\n"
        + json.dumps(complete_result())
    )

    parsed = gatekeeper._parse_json(content)

    assert parsed == complete_result()


def test_unclosed_reasoning_block_is_rejected():
    content = (
        "<think>Internal reasoning that never finishes..."
    )

    try:
        gatekeeper._parse_json(content)
    except ValueError as exc:
        assert "reasoning" in str(exc).lower()
    else:
        raise AssertionError(
            "Unclosed reasoning must not be accepted"
        )


def test_truncated_model_output_is_retryable(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": json.dumps(
                                complete_result()
                            )
                        },
                    }
                ]
            }

    monkeypatch.setattr(
        gatekeeper.httpx,
        "post",
        lambda *args, **kwargs: Response(),
    )

    result = gatekeeper.validate_definition(
        DESCRIPTION,
        [],
        settings(),
    )

    assert result["status"] == "unavailable"
    assert result["validated"] is False
    assert result["retryable"] is True
    assert result["complete"] is False
