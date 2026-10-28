from app.intake.helpers import (
    continue_helper,
    detect_helper_slot,
    format_helper_prompt,
    start_helper,
    wants_help,
)


def test_wants_help_and_detect_annual_value():
    text = "I want a finance chatbot but don't know its estimated annual value."
    assert wants_help(text)
    assert detect_helper_slot(text, ["annualValue", "name"]) == "annualValue"


def test_annual_value_helper_one_shot():
    state = {"helper": None, "slots": {}}
    prompt = start_helper(state, "annualValue")
    assert "How many queries" in prompt
    assert "I'll estimate" in prompt or "annual" in prompt.lower()

    answers = "\n".join(
        [
            "8000",
            "4 people, 10 hours",
            "50%",
            "12000",
            "free employee time",
        ]
    )
    result = continue_helper(state, answers)
    assert result["done"] is True
    assert "annualValue" in result["extraction"]
    value = result["extraction"]["annualValue"]["value"]
    assert value.isdigit()
    assert int(value) >= 1000
    assert state.get("helper") is None


def test_helper_prompt_lists_questions():
    body = format_helper_prompt("hoursSaved")
    assert "How many people" in body
    assert "hours saved" in body.lower() or "annual hours" in body.lower()
